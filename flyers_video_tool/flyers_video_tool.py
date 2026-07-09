import argparse
import csv
import json
import logging
import math
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from PIL import Image, ImageColor, ImageDraw, ImageFont


DEFAULT_PAGE_MAP: Dict[int, Dict[str, List[int]]] = {
    1: {
        "Part 1": [5],
        "Part 2": [6],
        "Part 3": [7, 8],
        "Part 4": [9, 10],
        "Part 5": [11],
    },
    2: {
        "Part 1": [23],
        "Part 2": [24],
        "Part 3": [25, 26],
        "Part 4": [27, 28],
        "Part 5": [29],
    },
    3: {
        "Part 1": [41],
        "Part 2": [42],
        "Part 3": [43, 44],
        "Part 4": [45, 46],
        "Part 5": [47],
    },
}

SUPPORTED_LEVELS = {"starters", "movers", "flyers"}
SUPPORTED_LAYOUTS = {"single", "side_by_side", "grid", "vertical", "auto"}
NUMBER_WORDS = {
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
    11: "eleven",
    12: "twelve",
    13: "thirteen",
    14: "fourteen",
    15: "fifteen",
    16: "sixteen",
    17: "seventeen",
    18: "eighteen",
    19: "nineteen",
    20: "twenty",
}

LOGGER = logging.getLogger("flyers_video_tool")
SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
SUPPORTED_TRANSITIONS = {"none", "crossfade", "fade", "slide"}
WATERMARK_POSITIONS = {"top-left", "top-right", "bottom-left", "bottom-right", "center"}
PAGE_MAP_STOP_PATTERNS = [
    r"\banswer\s+key\b",
    r"\banswers\b",
    r"\btranscript\b",
    r"\btapescript\b",
    r"\baudioscript\b",
    r"\breading\s*(?:and|&)\s*writing\b",
    r"\bspeaking\s+tests?\b",
]

def get_expected_part_count(level: str) -> int:
    lvl = level.lower()
    if lvl == "starters":
        return 4
    return 5

def _is_contents_page(text: str) -> bool:
    normalized = _normalize_text(text)
    if "contents" in normalized:
        return True
    # If it lists multiple sections, it's likely a contents page
    test_count = len(re.findall(r"\btest\s+\d+\b", normalized))
    if test_count >= 3:
        return True
    return False


def configure_logging(verbose: bool = True) -> None:
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(message)s")


def parse_resolution(value: str) -> Tuple[int, int]:
    match = re.fullmatch(r"\s*(\d{3,5})x(\d{3,5})\s*", value.lower())
    if not match:
        raise ValueError("Resolution must be formatted like 1920x1080 or 3840x2160.")
    width, height = int(match.group(1)), int(match.group(2))
    if width <= 0 or height <= 0:
        raise ValueError("Resolution width and height must be positive.")
    return width, height


def _legacy_page_map_to_config(level: str, test_number: int, page_map: Dict[int, Dict[str, List[int]]]) -> dict:
    if test_number not in page_map:
        raise ValueError(f"No preset page map for level={level}, test={test_number}. Provide --page-map.")
    parts = []
    for index, (title, pages) in enumerate(page_map[test_number].items(), start=1):
        layout = "single" if len(pages) == 1 else "side_by_side" if len(pages) == 2 else "grid"
        parts.append({"part": index, "title": title, "pages": list(pages), "layout": layout})
    return {"level": level.lower(), "test": test_number, "parts": parts}


def _starter_default_page_map(test_number: int) -> dict:
    base = 5 + (test_number - 1) * 18
    return {
        "level": "starters",
        "test": test_number,
        "parts": [
            {"part": 1, "title": "Part 1", "pages": [base], "layout": "single"},
            {"part": 2, "title": "Part 2", "pages": [base + 1], "layout": "single"},
            {"part": 3, "title": "Part 3", "pages": [base + 2, base + 3], "layout": "side_by_side"},
            {"part": 4, "title": "Part 4", "pages": [base + 4], "layout": "single"},
        ],
    }


def _movers_default_page_map(test_number: int) -> dict:
    flyers_like = _legacy_page_map_to_config("movers", test_number, DEFAULT_PAGE_MAP)
    flyers_like["level"] = "movers"
    return flyers_like


def get_preset_page_map(level: str = "flyers", test_number: int = 1) -> dict:
    normalized_level = (level or "flyers").lower()
    if normalized_level not in SUPPORTED_LEVELS:
        raise ValueError("Level must be starters, movers, or flyers.")
    if normalized_level == "starters":
        return normalize_page_map_config(_starter_default_page_map(test_number))
    if normalized_level == "movers":
        return normalize_page_map_config(_movers_default_page_map(test_number))
    return normalize_page_map_config(_legacy_page_map_to_config("flyers", test_number, DEFAULT_PAGE_MAP))


def normalize_page_map_config(config: dict) -> dict:
    if not isinstance(config, dict):
        raise ValueError("Page map config must be a JSON object.")
    level = str(config.get("level", "flyers")).lower()
    test_value = int(config.get("test", 1))
    
    parts = config.get("parts")
    result_config = {"level": level, "test": test_value}
    result_config["parts"] = parts

    pdf_offset = config.get("pdf_offset")
    if pdf_offset is not None:
        result_config["pdf_offset"] = pdf_offset
        for part in result_config["parts"]:
            if "pages" in part and not part.get("printed_pages"):
                part["printed_pages"] = [p - pdf_offset for p in part["pages"]]
    else:
        for part in result_config["parts"]:
            if "pages" in part and not part.get("printed_pages"):
                part["printed_pages"] = []

    if not result_config["parts"]:
        raise ValueError("Page map config must contain a non-empty parts list.")

    normalized_parts = []
    seen_part_numbers = set()
    for index, raw_part in enumerate(parts, start=1):
        part_number = int(raw_part.get("part", index))
        if part_number in seen_part_numbers:
            raise ValueError(f"Duplicate part number in page map: {part_number}")
        seen_part_numbers.add(part_number)
        title = str(raw_part.get("title") or f"Part {part_number}")
        
        pages = raw_part.get("pages")
        printed_pages = raw_part.get("printed_pages")

        if pages is None and printed_pages is not None and pdf_offset is not None:
            pages = [int(p) + pdf_offset for p in printed_pages]
        elif printed_pages is None and pages is not None and pdf_offset is not None:
            printed_pages = [int(p) - pdf_offset for p in pages]

        if not isinstance(pages, list) or not pages:
            raise ValueError(f"{title}: pages must be a non-empty list.")
            
        parsed_pages = [int(page) for page in pages]
        if any(page < 1 for page in parsed_pages):
            raise ValueError(f"{title}: PDF pages must start at 1.")
            
        layout = str(raw_part.get("layout") or "auto").lower()
        if layout not in SUPPORTED_LAYOUTS:
            raise ValueError(f"{title}: layout must be one of {', '.join(sorted(SUPPORTED_LAYOUTS))}.")
        if layout == "auto":
            if len(parsed_pages) == 1:
                layout = "single"
            elif len(parsed_pages) == 2:
                layout = "side_by_side"
            else:
                layout = "grid"
                
        part_dict = {"part": part_number, "title": title}
        if printed_pages is not None:
            part_dict["printed_pages"] = [int(p) for p in printed_pages]
        part_dict["pages"] = parsed_pages
        part_dict["layout"] = layout
        normalized_parts.append(part_dict)
        
    normalized_parts.sort(key=lambda item: item["part"])
    result = {"level": level, "test": test_value}
    if pdf_offset is not None:
        result["pdf_offset"] = pdf_offset
    result["parts"] = normalized_parts
    return result


def load_page_map_config(page_map_path: str | Path) -> dict:
    path = Path(page_map_path)
    if not path.exists():
        raise FileNotFoundError(f"Page map file not found: {path}")
    if path.suffix.lower() != ".json":
        raise ValueError("Only JSON page map files are supported for now.")
    with path.open("r", encoding="utf-8-sig") as handle:
        return normalize_page_map_config(json.load(handle))


def export_page_map_config(config: dict, output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = normalize_page_map_config(config)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(normalized, handle, ensure_ascii=False, indent=2)
    LOGGER.info("Exported page map JSON: %s", path)
    return path


def detect_part_heading_in_text(text: str) -> Optional[int]:
    normalized = _normalize_text(text)
    for number, word in NUMBER_WORDS.items():
        patterns = [
            rf"\bpart\s+{number}\b",
            rf"\bpart\s+{re.escape(word)}\b",
        ]
        if any(re.search(pattern, normalized) for pattern in patterns):
            return number
    numeric_match = re.search(r"\bpart\s+(\d{1,2})\b", normalized)
    if numeric_match:
        return int(numeric_match.group(1))
    return None


def _is_page_map_stop_page(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(re.search(pattern, normalized) for pattern in PAGE_MAP_STOP_PATTERNS)


def _default_layout_for_page_count(page_count: int) -> str:
    if page_count <= 1:
        return "single"
    if page_count == 2:
        return "side_by_side"
    return "grid"


def build_page_map_from_ocr_results(
    ocr_results: Sequence[dict],
    level: str = "flyers",
    test_number: int = 1,
    start_page: Optional[int] = None,
    max_page: Optional[int] = None,
    min_confidence: float = 55.0,
    printed_start_page: Optional[int] = None,
) -> Tuple[dict, List[str]]:
    if not ocr_results:
        raise ValueError("OCR results are empty. Cannot build page map.")

    sorted_results = sorted(
        [
            item
            for item in ocr_results
            if (start_page is None or int(item["page"]) >= start_page)
            and (max_page is None or int(item["page"]) <= max_page)
        ],
        key=lambda item: int(item["page"]),
    )
    if not sorted_results:
        raise ValueError("No OCR pages remain after applying the requested page range.")
    warnings: List[str] = []
    
    expected_part_count = get_expected_part_count(level)
    
    # Phase A: Detect Part 1 and other Parts
    part_starts: Dict[int, dict] = {}
    
    for result in sorted_results:
        page_number = int(result["page"])
        text = str(result.get("text", ""))
        heading_text = str(result.get("heading_text") or "")
        normalized_heading = _normalize_text(heading_text)
        normalized_text = _normalize_text(text)
        is_contents = _is_contents_page(text)
        has_stop = _is_page_map_stop_page(text) or _is_page_map_stop_page(heading_text)
        
        part_number = detect_part_heading_in_text(heading_text) if heading_text else None
        matched_in_heading = part_number is not None
        
        if part_number is None:
            # Fallback to full page text ONLY if strong conditions are met
            if not is_contents and not has_stop:
                if 1 in part_starts:
                    part_number = detect_part_heading_in_text(text)
                else:
                    if "listening" in normalized_text and "test" in normalized_text:
                        part_number = detect_part_heading_in_text(text)
        
        if part_number is not None:
            if part_number > expected_part_count:
                continue # Ignore parts beyond expected count
            
            # Avoid detecting parts on contents or pages with stop words before part 1 is found
            if 1 not in part_starts and (is_contents or has_stop):
                # Strong requirement: If we haven't found Part 1, we must ignore part numbers on Contents pages or stop pages
                continue
                
            confidence = float(result.get("confidence", 100.0) or 0.0)
            score = confidence + (25 if matched_in_heading else 0)
            
            if "listening" in normalized_heading or "listening" in normalized_text:
                score += 15
            if "question" in normalized_heading or "questions" in normalized_text:
                score += 5
            if "look and listen" in normalized_text:
                score += 5
                
            unwanted = ["reading and writing", "answer key", "answers", "transcript", "audioscript", "tapescript", "speaking test"]
            for bad_word in unwanted:
                if bad_word in normalized_heading or bad_word in normalized_text:
                    score -= 50

            if confidence < min_confidence:
                warnings.append(
                    f"Part {part_number} heading on page {page_number} has low OCR confidence ({confidence:.1f})."
                )
            
            # Record the best candidate for each part number based on score and page order
            # We want the *first* occurrence with the highest score
            if part_number not in part_starts:
                part_starts[part_number] = {"page": page_number, "score": score}
            else:
                existing = part_starts[part_number]
                # Allow replacing if it's a substantially better score (e.g. heading match vs full-text match)
                if score > existing["score"] + 20 and page_number > existing["page"]:
                     part_starts[part_number] = {"page": page_number, "score": score}

    if not part_starts:
        warnings.append("No Part headings were detected by OCR. Please enter the page map manually.")
        return {"level": level.lower(), "test": int(test_number), "parts": []}, warnings

    found_parts = sorted(part_starts.keys())
    for expected in range(found_parts[0], found_parts[-1] + 1):
        if expected not in part_starts:
            warnings.append(f"Missing heading for Part {expected}. Please review the page map manually.")

    # Phase B: Find Stop Page
    part1_page = part_starts[found_parts[0]]["page"]
    stop_page: Optional[int] = None
    
    for result in sorted_results:
        page_number = int(result["page"])
        if page_number <= part1_page:
            continue
        text = str(result.get("text", ""))
        heading_text = str(result.get("heading_text") or "")
        is_contents = _is_contents_page(text)
        
        if not is_contents:
            if _is_page_map_stop_page(text) or _is_page_map_stop_page(heading_text):
                stop_page = page_number
                break

    page_numbers = [int(item["page"]) for item in sorted_results]
    last_scanned_page = max(page for page in page_numbers if max_page is None or page <= max_page)

    pdf_offset = None
    if printed_start_page is not None and 1 in part_starts:
        pdf_offset = part_starts[1]["page"] - printed_start_page

    parts = []
    ordered_starts = [(part, part_starts[part]["page"]) for part in found_parts]
    for index, (part_number, start_page_num) in enumerate(ordered_starts):
        if index < len(ordered_starts) - 1:
            end_page_num = ordered_starts[index + 1][1] - 1
        else:
            # Final expected Listening part
            if stop_page is not None:
                end_page_num = stop_page - 1
            else:
                warnings.append("Could not determine end of final Listening part. Defaulted to one page. Please review manually.")
                end_page_num = start_page_num
                
        if end_page_num < start_page_num:
            warnings.append(f"Part {part_number} has invalid page range. Please review manually.")
            pages = [start_page_num]
        else:
            pages = list(range(start_page_num, end_page_num + 1))
            
        # Validation checks
        if len(pages) > 2:
            warnings.append(f"Suspicious page range. Part {part_number} has {len(pages)} pages. This likely includes non-Listening pages. Please review.")
        if index == len(ordered_starts) - 1 and len(pages) > 1:
            warnings.append(f"Suspicious page range. Final Part {part_number} has {len(pages)} pages. Please review.")
            
        layout = _default_layout_for_page_count(len(pages))
        if layout == "grid":
            warnings.append(f"Part {part_number} layout detected as grid ({len(pages)} pages). Please review manually.")
            
        part_dict = {
            "part": part_number,
            "title": f"Part {part_number}",
            "pages": pages,
            "layout": layout,
        }
        if pdf_offset is not None:
            part_dict["printed_pages"] = [p - pdf_offset for p in pages]
        parts.append(part_dict)

    result_config = {"level": level.lower(), "test": int(test_number), "parts": parts}
    if pdf_offset is not None:
        result_config["pdf_offset"] = pdf_offset
    return normalize_page_map_config(result_config), warnings



def ocr_pdf_pages(
    pdf_path: str | Path,
    output_dir: str | Path,
    render_scale: float = 2.0,
    start_page: int = 1,
    end_page: Optional[int] = None,
    engine: str = "tesseract",
    language: str = "eng",
) -> List[dict]:
    if engine.lower() != "tesseract":
        raise ValueError("Only local Tesseract OCR is currently implemented. Use --ocr-engine tesseract.")
    try:
        import pytesseract
        import os
        if os.name == "nt" and Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe").exists():
            pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    except ImportError as exc:
        raise RuntimeError("Missing dependency pytesseract. Install with: pip install -r requirements.txt") from exc

    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF file not found: {path}")
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("Missing dependency pymupdf. Install with: pip install -r requirements.txt") from exc

    with fitz.open(path) as document:
        total_pages = document.page_count
    final_page = min(end_page or total_pages, total_pages)
    if start_page < 1 or start_page > final_page:
        raise ValueError("Invalid OCR page range.")

    results = []
    page_dir = Path(output_dir) / "ocr_pages"
    page_dir.mkdir(parents=True, exist_ok=True)
    for page_number in range(start_page, final_page + 1):
        image_path = render_pdf_page(path, page_number, page_dir, render_scale)
        with Image.open(image_path) as image:
            data = pytesseract.image_to_data(image, lang=language, output_type=pytesseract.Output.DICT)
        words = []
        heading_words = []
        confidences = []
        page_height = image.height
        for word, confidence, top in zip(data.get("text", []), data.get("conf", []), data.get("top", [])):
            clean_word = str(word).strip()
            if clean_word:
                words.append(clean_word)
                try:
                    if float(top) <= page_height * 0.45:
                        heading_words.append(clean_word)
                except ValueError:
                    pass
                try:
                    conf_value = float(confidence)
                    if conf_value >= 0:
                        confidences.append(conf_value)
                except ValueError:
                    pass
        text = " ".join(words)
        heading_text = " ".join(heading_words)
        average_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        results.append({"page": page_number, "text": text, "heading_text": heading_text, "confidence": average_confidence})
    return results


def auto_detect_page_map_from_pdf(
    pdf_path: str | Path,
    output_dir: str | Path,
    level: str = "flyers",
    test_number: int = 1,
    render_scale: float = 2.0,
    start_page: int = 1,
    end_page: Optional[int] = None,
    ocr_engine: str = "tesseract",
    ocr_language: str = "eng",
    min_confidence: float = 55.0,
    printed_start_page: Optional[int] = None,
) -> Tuple[dict, List[str], List[dict]]:
    if end_page is None:
        raise ValueError(
            "Auto page map requires a bounded Listening page range. "
            "Set --ocr-end-page or --listening-end-page to avoid scanning the whole PDF."
        )
    LOGGER.info("Auto detecting page map with local OCR...")
    ocr_results = ocr_pdf_pages(
        pdf_path=pdf_path,
        output_dir=output_dir,
        render_scale=render_scale,
        start_page=start_page,
        end_page=end_page,
        engine=ocr_engine,
        language=ocr_language,
    )
    config, warnings = build_page_map_from_ocr_results(
        ocr_results,
        level=level,
        test_number=test_number,
        max_page=end_page,
        min_confidence=min_confidence,
        printed_start_page=printed_start_page,
    )
    return config, warnings, ocr_results


def resolve_page_map_config(
    level: str = "flyers",
    test_number: int = 1,
    page_map_path: Optional[str | Path] = None,
    fallback_config: Optional[dict] = None,
) -> dict:
    if page_map_path:
        return load_page_map_config(page_map_path)
    if fallback_config:
        return normalize_page_map_config(fallback_config)
    return get_preset_page_map(level, test_number)


def normalize_watermark_options(
    enabled: bool = False,
    text: Optional[str] = None,
    image: Optional[str | Path] = None,
    position: str = "bottom-right",
    opacity: float = 0.35,
    size: int = 120,
    margin: int = 32,
) -> dict:
    if not enabled:
        return {
            "enabled": False,
            "text": None,
            "image": None,
            "position": "bottom-right",
            "opacity": 0.0,
            "size": size,
            "margin": margin,
        }
    if position not in WATERMARK_POSITIONS:
        raise ValueError(f"Watermark position must be one of: {', '.join(sorted(WATERMARK_POSITIONS))}.")
    if not text and not image:
        raise ValueError("Enable watermark requires watermark text or watermark PNG image.")
    if image and not Path(image).exists():
        raise FileNotFoundError(f"Watermark image not found: {image}")
    if not 0 <= float(opacity) <= 1:
        raise ValueError("Watermark opacity must be between 0 and 1.")
    if int(size) <= 0:
        raise ValueError("Watermark size must be greater than zero.")
    if int(margin) < 0:
        raise ValueError("Watermark margin cannot be negative.")
    return {
        "enabled": True,
        "text": text,
        "image": str(image) if image else None,
        "position": position,
        "opacity": float(opacity),
        "size": int(size),
        "margin": int(margin),
    }


def parse_timestamp(value: str) -> float:
    raw = str(value).strip()
    if not raw:
        raise ValueError("Timestamp is empty.")
    parts = raw.split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"Invalid timestamp '{value}'. Use MM:SS or HH:MM:SS.")
    try:
        numbers = [float(part) for part in parts]
    except ValueError as exc:
        raise ValueError(f"Invalid timestamp '{value}'.") from exc

    if any(number < 0 for number in numbers):
        raise ValueError(f"Timestamp cannot be negative: '{value}'.")
    if len(parts) == 2:
        minutes, seconds = numbers
        return minutes * 60 + seconds
    hours, minutes, seconds = numbers
    return hours * 3600 + minutes * 60 + seconds


def format_timestamp(seconds: float) -> str:
    total = max(0, int(round(float(seconds))))
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def get_audio_duration(audio_path: str | Path) -> float:
    path = Path(audio_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {path}")
    try:
        from pydub import AudioSegment
    except ImportError as exc:
        raise RuntimeError("Missing dependency pydub. Install with: pip install -r requirements.txt") from exc

    audio = AudioSegment.from_file(path)
    return len(audio) / 1000.0


def _collect_files(input_dir: Optional[str | Path], explicit_files: Optional[Sequence[str | Path]], suffixes: set) -> Dict[str, Path]:
    files: List[Path] = []
    if input_dir:
        root = Path(input_dir)
        if not root.exists():
            raise FileNotFoundError(f"Input directory not found: {root}")
        if not root.is_dir():
            raise NotADirectoryError(f"Input path is not a directory: {root}")
        files.extend(path for path in root.iterdir() if path.is_file() and path.suffix.lower() in suffixes)
    if explicit_files:
        for raw in explicit_files:
            path = Path(raw)
            if not path.exists():
                raise FileNotFoundError(f"Batch input file not found: {path}")
            if path.suffix.lower() in suffixes:
                files.append(path)

    by_stem: Dict[str, Path] = {}
    for path in sorted(files, key=lambda item: item.name.lower()):
        by_stem.setdefault(path.stem, path)
    return by_stem


def discover_batch_pairs(
    input_dir: Optional[str | Path] = None,
    pdfs: Optional[Sequence[str | Path]] = None,
    audios: Optional[Sequence[str | Path]] = None,
    output_dir: Optional[str | Path] = None,
) -> Tuple[List[dict], List[str]]:
    pdf_by_stem = _collect_files(input_dir, pdfs, {".pdf"})
    audio_by_stem = _collect_files(input_dir, audios, SUPPORTED_AUDIO_EXTENSIONS)
    all_stems = sorted(set(pdf_by_stem) | set(audio_by_stem), key=str.lower)
    output_root = Path(output_dir) if output_dir else Path.cwd() / "outputs"

    pairs: List[dict] = []
    warnings: List[str] = []
    for stem in all_stems:
        pdf_path = pdf_by_stem.get(stem)
        audio_path = audio_by_stem.get(stem)
        if pdf_path and audio_path:
            pairs.append(
                {
                    "base_name": stem,
                    "pdf_path": pdf_path,
                    "audio_path": audio_path,
                    "output_path": output_root / f"{stem}.mp4",
                    "status": "matched",
                }
            )
        elif pdf_path:
            warnings.append(f"Missing MP3 for '{stem}'. Skipping.")
        elif audio_path:
            warnings.append(f"Missing PDF for '{stem}'. Skipping.")
    return pairs, warnings


def _resolve_pairing_path(base_dir: Path, value: str) -> Path:
    path = Path(str(value).strip())
    if not path.is_absolute():
        path = base_dir / path
    return path


def read_pairing_csv(pairing_csv: str | Path, output_dir: Optional[str | Path] = None) -> List[dict]:
    path = Path(pairing_csv)
    if not path.exists():
        raise FileNotFoundError(f"Pairing CSV not found: {path}")
    output_root = Path(output_dir) if output_dir else path.parent / "outputs"
    pairs: List[dict] = []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"pdf", "audio", "output_name"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise ValueError("pairing.csv must include columns: pdf,audio,output_name")
        for line_number, row in enumerate(reader, start=2):
            pdf_path = _resolve_pairing_path(path.parent, row.get("pdf", ""))
            audio_path = _resolve_pairing_path(path.parent, row.get("audio", ""))
            output_name = (row.get("output_name") or pdf_path.stem).strip()
            if not output_name:
                raise ValueError(f"pairing.csv line {line_number}: output_name is empty.")
            level = (row.get("level") or "flyers").strip().lower()
            try:
                active_test = int(str(row.get("test") or "1").strip())
            except ValueError as exc:
                raise ValueError(f"pairing.csv line {line_number}: test must be 1, 2, or 3.") from exc
            if not pdf_path.exists():
                raise FileNotFoundError(f"pairing.csv line {line_number}: PDF not found: {pdf_path}")
            if not audio_path.exists():
                raise FileNotFoundError(f"pairing.csv line {line_number}: audio not found: {audio_path}")
            page_map_path = None
            page_map_config = None
            raw_page_map = (row.get("page_map") or "").strip()
            if raw_page_map:
                page_map_path = _resolve_pairing_path(path.parent, raw_page_map)
                page_map_config = load_page_map_config(page_map_path)
            raw_ocr_start = (row.get("ocr_start_page") or "").strip()
            raw_ocr_end = (row.get("ocr_end_page") or "").strip()
            raw_printed_start = (row.get("printed_start_page") or "").strip()
            ocr_start_page = int(raw_ocr_start) if raw_ocr_start else None
            ocr_end_page = int(raw_ocr_end) if raw_ocr_end else None
            printed_start_page = int(raw_printed_start) if raw_printed_start else None
            pairs.append(
                {
                    "base_name": output_name,
                    "pdf_path": pdf_path,
                    "audio_path": audio_path,
                    "output_path": output_root / f"{output_name}.mp4",
                    "level": level,
                    "test_number": active_test,
                    "page_map_path": page_map_path,
                    "page_map_config": page_map_config,
                    "ocr_start_page": ocr_start_page,
                    "ocr_end_page": ocr_end_page,
                    "printed_start_page": printed_start_page,
                    "status": "matched",
                }
            )
    return pairs


def infer_test_number_from_name(name: str, default: int = 1) -> int:
    match = re.search(r"\btest\s*([123])\b", name, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    return default


def transcribe_audio(
    audio_path: str | Path,
    whisper_model: str = "small",
    language: str = "en",
    device: str = "auto",
    compute_type: str = "default",
) -> List[dict]:
    path = Path(audio_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {path}")
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency faster-whisper. Install with: pip install -r requirements.txt"
        ) from exc

    LOGGER.info("Transcribing audio with faster-whisper local model '%s'...", whisper_model)
    model = WhisperModel(whisper_model, device=device, compute_type=compute_type)
    segments_iter, _info = model.transcribe(
        str(path),
        language=language or None,
        word_timestamps=True,
        vad_filter=True,
    )

    segments = []
    for segment in segments_iter:
        item = {
            "start": float(segment.start),
            "end": float(segment.end),
            "text": segment.text.strip(),
        }
        words = getattr(segment, "words", None)
        if words:
            item["words"] = [
                {"start": float(word.start), "end": float(word.end), "word": word.word}
                for word in words
            ]
        segments.append(item)
    return segments


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


def _segment_mentions_part(segment: dict, part_number: int) -> bool:
    text = _normalize_text(segment.get("text", ""))
    word = NUMBER_WORDS.get(part_number, str(part_number))
    aliases = [
        f"part {word}",
        f"part {part_number}",
        f"now listen to part {word}",
        f"now listen to part {part_number}",
        f"look at part {word}",
        f"look at part {part_number}",
    ]
    aliases = sorted(aliases, key=len, reverse=True)
    return any(re.search(rf"\b{re.escape(_normalize_text(alias))}\b", text) for alias in aliases)


def _find_part_start(segments: Sequence[dict], part_number: int, after: float) -> Optional[float]:
    for segment in segments:
        start = float(segment.get("start", 0.0))
        end = float(segment.get("end", start))
        if end + 0.01 < after:
            continue
        if _segment_mentions_part(segment, part_number):
            return max(start, after)
    return None


def detect_part_timestamps(
    segments: Sequence[dict],
    audio_duration: float,
    test_number: int = 1,
    page_map: Dict[int, Dict[str, List[int]]] = DEFAULT_PAGE_MAP,
    page_map_config: Optional[dict] = None,
) -> Tuple[List[dict], List[str]]:
    if page_map_config is None:
        config = _legacy_page_map_to_config("flyers", test_number, page_map)
    else:
        config = normalize_page_map_config(page_map_config)
    if audio_duration <= 0:
        raise ValueError("Audio duration must be greater than zero.")

    rows: List[dict] = []
    warnings: List[str] = []
    detected_starts: List[float] = []
    search_after = 0.0

    for part in config["parts"]:
        part_number = int(part["part"])
        start = _find_part_start(segments, part_number, search_after)
        if start is None:
            if not detected_starts:
                start = 0.0
                warnings.append(f"{part['title']} was not detected. Using 00:00 as fallback.")
            else:
                start = detected_starts[-1] if detected_starts else 0.0
                warnings.append(f"{part['title']} was not detected. Please review the CSV manually.")
        detected_starts.append(start)
        search_after = start + 1.0
        LOGGER.info("Detected %s at %s", part["title"], format_timestamp(start))

    for index, part in enumerate(config["parts"]):
        title = part["title"]
        start = detected_starts[index]
        end = detected_starts[index + 1] if index < len(config["parts"]) - 1 else float(audio_duration)
        if end <= start:
            warnings.append(f"{title} has non-positive duration. Please edit detected_timestamps.csv.")
        rows.append(
            {
                "title": title,
                "part": part["part"],
                "start_seconds": start,
                "end_seconds": end,
                "pdf_pages": part["pages"],
                "layout": part["layout"],
            }
        )
    return rows, warnings


def export_detected_timestamps(rows: Sequence[dict], output_csv: str | Path) -> Path:
    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["title", "start", "end", "pdf_pages", "layout"])
        writer.writeheader()
        for row in rows:
            pages = ",".join(str(page) for page in row["pdf_pages"])
            layout = row.get("layout")
            if not layout:
                layout = "single" if len(row["pdf_pages"]) == 1 else "side_by_side" if len(row["pdf_pages"]) == 2 else "grid"
            writer.writerow(
                {
                    "title": row["title"],
                    "start": format_timestamp(row["start_seconds"]),
                    "end": format_timestamp(row["end_seconds"]),
                    "pdf_pages": pages,
                    "layout": layout,
                }
            )
    LOGGER.info("Exported timestamp CSV: %s", output_path)
    return output_path


def _parse_pages(value: str) -> List[int]:
    pages = []
    for part in str(value).replace(";", ",").split(","):
        raw = part.strip().strip('"').strip("'")
        if not raw:
            continue
        pages.append(int(raw))
    if not pages:
        raise ValueError("pdf_pages must contain at least one page.")
    return pages


def parse_timestamps_csv(csv_path: str | Path) -> List[dict]:
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Timestamp CSV not found: {path}")

    rows: List[dict] = []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"title", "start", "end", "pdf_pages"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise ValueError("CSV must include columns: title,start,end,pdf_pages")
        for line_number, row in enumerate(reader, start=2):
            title = (row.get("title") or "").strip()
            start = parse_timestamp(row.get("start", ""))
            end = parse_timestamp(row.get("end", ""))
            if end <= start:
                raise ValueError(f"CSV line {line_number}: end must be greater than start.")
            pages = _parse_pages(row.get("pdf_pages", ""))
            layout = (row.get("layout") or "auto").strip().lower()
            if layout == "auto":
                layout = "single" if len(pages) == 1 else "side_by_side" if len(pages) == 2 else "grid"
            if layout not in SUPPORTED_LAYOUTS - {"auto"}:
                raise ValueError(f"CSV line {line_number}: invalid layout '{layout}'.")
            rows.append(
                {
                    "title": title,
                    "start_seconds": start,
                    "end_seconds": end,
                    "pdf_pages": pages,
                    "layout": layout,
                }
            )
    if not rows:
        raise ValueError("Timestamp CSV contains no rows.")
    return rows


def _background_rgb(background: str) -> Tuple[int, int, int]:
    if background.lower() == "dark":
        return (28, 30, 34)
    if background.lower() == "white":
        return (255, 255, 255)
    try:
        return ImageColor.getrgb(background)
    except ValueError as exc:
        raise ValueError("Background must be 'white', 'dark', or a valid CSS color.") from exc


def render_pdf_page(
    pdf_path: str | Path,
    page_number: int,
    output_dir: str | Path,
    render_scale: float = 3.0,
) -> Path:
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF file not found: {path}")
    if page_number < 1:
        raise ValueError("PDF page number starts at 1.")
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("Missing dependency pymupdf. Install with: pip install -r requirements.txt") from exc

    output_path = Path(output_dir) / f"page_{page_number:03d}.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    LOGGER.info("Rendering PDF page %s...", page_number)
    with fitz.open(path) as document:
        if page_number > document.page_count:
            raise ValueError(f"PDF page {page_number} is out of range. PDF has {document.page_count} pages.")
        page = document.load_page(page_number - 1)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(render_scale, render_scale), alpha=False)
        pixmap.save(output_path)
    return output_path


def _fit_image(image: Image.Image, max_width: int, max_height: int) -> Image.Image:
    fitted = image.copy()
    fitted.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
    return fitted


def make_single_page_scene(
    page_image_path: str | Path,
    output_path: str | Path,
    resolution: Tuple[int, int] = (1920, 1080),
    background: str = "white",
    margin_ratio: float = 0.035,
) -> Path:
    width, height = resolution
    bg = _background_rgb(background)
    canvas = Image.new("RGB", resolution, bg)
    margin = max(24, int(min(width, height) * margin_ratio))
    with Image.open(page_image_path) as image:
        fitted = _fit_image(image.convert("RGB"), width - margin * 2, height - margin * 2)
    x = (width - fitted.width) // 2
    y = (height - fitted.height) // 2
    canvas.paste(fitted, (x, y))
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, quality=96)
    return path


def make_double_page_scene(
    left_page_image_path: str | Path,
    right_page_image_path: str | Path,
    output_path: str | Path,
    resolution: Tuple[int, int] = (1920, 1080),
    background: str = "white",
    open_book_gap: int = 24,
    margin_ratio: float = 0.035,
) -> Path:
    width, height = resolution
    bg = _background_rgb(background)
    canvas = Image.new("RGB", resolution, bg)
    margin = max(24, int(min(width, height) * margin_ratio))
    available_width = width - margin * 2 - open_book_gap
    available_height = height - margin * 2

    with Image.open(left_page_image_path) as left_raw, Image.open(right_page_image_path) as right_raw:
        left = left_raw.convert("RGB")
        right = right_raw.convert("RGB")
        left_ratio = left.width / left.height
        right_ratio = right.width / right.height
        target_height = min(available_height, int(available_width / (left_ratio + right_ratio)))
        left_size = (max(1, int(target_height * left_ratio)), target_height)
        right_size = (max(1, int(target_height * right_ratio)), target_height)
        left_resized = left.resize(left_size, Image.Resampling.LANCZOS)
        right_resized = right.resize(right_size, Image.Resampling.LANCZOS)

    total_width = left_resized.width + open_book_gap + right_resized.width
    x = (width - total_width) // 2
    y = (height - target_height) // 2
    canvas.paste(left_resized, (x, y))
    canvas.paste(right_resized, (x + left_resized.width + open_book_gap, y))
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, quality=96)
    return path


def make_grid_page_scene(
    page_image_paths: Sequence[str | Path],
    output_path: str | Path,
    resolution: Tuple[int, int] = (1920, 1080),
    background: str = "white",
    gap: int = 24,
    margin_ratio: float = 0.035,
) -> Path:
    if not page_image_paths:
        raise ValueError("Grid scene requires at least one page image.")
    width, height = resolution
    bg = _background_rgb(background)
    canvas = Image.new("RGB", resolution, bg)
    margin = max(24, int(min(width, height) * margin_ratio))
    count = len(page_image_paths)
    cols = math.ceil(math.sqrt(count))
    rows = math.ceil(count / cols)
    cell_width = (width - margin * 2 - gap * (cols - 1)) // cols
    cell_height = (height - margin * 2 - gap * (rows - 1)) // rows
    with_images = []
    for image_path in page_image_paths:
        with Image.open(image_path) as image:
            with_images.append(_fit_image(image.convert("RGB"), cell_width, cell_height))
    for index, image in enumerate(with_images):
        row = index // cols
        col = index % cols
        cell_x = margin + col * (cell_width + gap)
        cell_y = margin + row * (cell_height + gap)
        x = cell_x + (cell_width - image.width) // 2
        y = cell_y + (cell_height - image.height) // 2
        canvas.paste(image, (x, y))
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, quality=96)
    return path


def make_vertical_page_scene(
    page_image_paths: Sequence[str | Path],
    output_path: str | Path,
    resolution: Tuple[int, int] = (1920, 1080),
    background: str = "white",
    gap: int = 24,
    margin_ratio: float = 0.035,
) -> Path:
    if not page_image_paths:
        raise ValueError("Vertical scene requires at least one page image.")
    width, height = resolution
    bg = _background_rgb(background)
    canvas = Image.new("RGB", resolution, bg)
    margin = max(24, int(min(width, height) * margin_ratio))
    count = len(page_image_paths)
    cell_height = (height - margin * 2 - gap * (count - 1)) // count
    cell_width = width - margin * 2
    images = []
    for image_path in page_image_paths:
        with Image.open(image_path) as image:
            images.append(_fit_image(image.convert("RGB"), cell_width, cell_height))
    total_height = sum(image.height for image in images) + gap * (count - 1)
    y = (height - total_height) // 2
    for image in images:
        x = (width - image.width) // 2
        canvas.paste(image, (x, y))
        y += image.height + gap
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, quality=96)
    return path


def make_pages_scene(
    page_image_paths: Sequence[str | Path],
    output_path: str | Path,
    layout: str = "auto",
    resolution: Tuple[int, int] = (1920, 1080),
    background: str = "white",
    open_book_gap: int = 24,
) -> Path:
    paths = list(page_image_paths)
    if not paths:
        raise ValueError("Scene requires at least one page.")
    effective_layout = layout or "auto"
    if effective_layout == "auto":
        effective_layout = "single" if len(paths) == 1 else "side_by_side" if len(paths) == 2 else "grid"
    if effective_layout == "single":
        if len(paths) != 1:
            return make_grid_page_scene(paths, output_path, resolution, background, open_book_gap)
        return make_single_page_scene(paths[0], output_path, resolution, background)
    if effective_layout == "side_by_side":
        if len(paths) != 2:
            return make_grid_page_scene(paths, output_path, resolution, background, open_book_gap)
        return make_double_page_scene(paths[0], paths[1], output_path, resolution, background, open_book_gap)
    if effective_layout == "grid":
        return make_grid_page_scene(paths, output_path, resolution, background, open_book_gap)
    if effective_layout == "vertical":
        return make_vertical_page_scene(paths, output_path, resolution, background, open_book_gap)
    raise ValueError(f"Unsupported scene layout: {layout}")


def _watermark_position(canvas_size: Tuple[int, int], mark_size: Tuple[int, int], position: str, margin: int) -> Tuple[int, int]:
    width, height = canvas_size
    mark_width, mark_height = mark_size
    if position == "top-left":
        return margin, margin
    if position == "top-right":
        return width - mark_width - margin, margin
    if position == "bottom-left":
        return margin, height - mark_height - margin
    if position == "bottom-right":
        return width - mark_width - margin, height - mark_height - margin
    return (width - mark_width) // 2, (height - mark_height) // 2


def _load_font(size: int):
    candidates = [
        "arial.ttf",
        "DejaVuSans-Bold.ttf",
        "DejaVuSans.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def apply_watermark_to_scene(
    scene_path: str | Path,
    output_path: str | Path,
    watermark_options: dict,
) -> Path:
    options = normalize_watermark_options(**watermark_options)
    source = Path(scene_path)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not options["enabled"]:
        if source != target:
            with Image.open(source) as image:
                image.convert("RGB").save(target, quality=96)
        return target

    with Image.open(source) as raw:
        canvas = raw.convert("RGBA")

    opacity = int(255 * options["opacity"])
    if options["image"]:
        with Image.open(options["image"]) as wm_raw:
            watermark = wm_raw.convert("RGBA")
            watermark.thumbnail((options["size"], options["size"]), Image.Resampling.LANCZOS)
            alpha = watermark.getchannel("A").point(lambda value: int(value * options["opacity"]))
            watermark.putalpha(alpha)
    else:
        font = _load_font(options["size"])
        text = str(options["text"])
        probe = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        draw = ImageDraw.Draw(probe)
        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=2)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        watermark = Image.new("RGBA", (text_width + 12, text_height + 12), (0, 0, 0, 0))
        draw = ImageDraw.Draw(watermark)
        draw.text(
            (6, 6 - bbox[1]),
            text,
            font=font,
            fill=(255, 255, 255, opacity),
            stroke_width=2,
            stroke_fill=(0, 0, 0, max(0, opacity - 40)),
        )

    x, y = _watermark_position(canvas.size, watermark.size, options["position"], options["margin"])
    canvas.alpha_composite(watermark, (x, y))
    canvas.convert("RGB").save(target, quality=96)
    return target


def _transition_frames(
    previous_scene: str | Path,
    next_scene: str | Path,
    output_dir: str | Path,
    transition_effect: str,
    transition_duration: float,
    fps: int,
    background: str,
) -> List[str]:
    effect = transition_effect.lower()
    if effect not in SUPPORTED_TRANSITIONS:
        raise ValueError(f"Transition effect must be one of: {', '.join(sorted(SUPPORTED_TRANSITIONS))}.")
    if effect == "none" or transition_duration <= 0:
        return []

    frame_count = max(2, int(round(transition_duration * fps)))
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    bg = _background_rgb(background)
    frame_paths: List[str] = []

    with Image.open(previous_scene) as prev_raw, Image.open(next_scene) as next_raw:
        prev = prev_raw.convert("RGB")
        nxt = next_raw.convert("RGB").resize(prev.size, Image.Resampling.LANCZOS)
        width, height = prev.size
        for index in range(frame_count):
            alpha = (index + 1) / (frame_count + 1)
            if effect == "crossfade":
                frame = Image.blend(prev, nxt, alpha)
            elif effect == "fade":
                if alpha < 0.5:
                    local = alpha / 0.5
                    frame = Image.blend(prev, Image.new("RGB", prev.size, bg), local)
                else:
                    local = (alpha - 0.5) / 0.5
                    frame = Image.blend(Image.new("RGB", prev.size, bg), nxt, local)
            elif effect == "slide":
                frame = Image.new("RGB", prev.size, bg)
                offset = int(width * alpha)
                frame.paste(prev, (-offset, 0))
                frame.paste(nxt, (width - offset, 0))
            else:
                frame = nxt.copy()
            frame_path = output_root / f"transition_{index:04d}.jpg"
            frame.save(frame_path, quality=94)
            frame_paths.append(str(frame_path))
    return frame_paths


def _check_ffmpeg_available() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("FFmpeg was not found in PATH. Install FFmpeg and restart the terminal.")


def _validate_timestamp_rows(rows: Sequence[dict]) -> None:
    previous_end = -math.inf
    for row in rows:
        title = row.get("title", "Untitled")
        start = float(row["start_seconds"])
        end = float(row["end_seconds"])
        pages = row.get("pdf_pages", [])
        if end <= start:
            raise ValueError(f"{title}: timestamp end must be greater than start.")
        if start < previous_end - 0.5:
            raise ValueError(f"{title}: timestamp overlaps the previous part.")
        if not pages:
            raise ValueError(f"{title}: pdf_pages must contain at least one page.")
        layout = row.get("layout") or "auto"
        if layout not in SUPPORTED_LAYOUTS:
            raise ValueError(f"{title}: invalid layout '{layout}'.")
        previous_end = end


def _moviepy_imports():
    try:
        from moviepy.editor import AudioFileClip, ImageClip, ImageSequenceClip, concatenate_videoclips
    except ImportError:
        try:
            from moviepy import AudioFileClip, ImageClip, ImageSequenceClip, concatenate_videoclips
        except ImportError as exc:
            raise RuntimeError("Missing dependency moviepy. Install with: pip install -r requirements.txt") from exc
    return AudioFileClip, ImageClip, ImageSequenceClip, concatenate_videoclips


def _clip_with_duration(image_clip, duration: float):
    if hasattr(image_clip, "with_duration"):
        return image_clip.with_duration(duration)
    return image_clip.set_duration(duration)


def _clip_with_audio(video_clip, audio_clip):
    if hasattr(video_clip, "with_audio"):
        return video_clip.with_audio(audio_clip)
    return video_clip.set_audio(audio_clip)


def _clip_subclip(audio_clip, start: float, end: float):
    if hasattr(audio_clip, "subclipped"):
        return audio_clip.subclipped(start, end)
    return audio_clip.subclip(start, end)


def build_timeline_segments(
    durations: Sequence[float],
    transition_effect: str = "crossfade",
    transition_duration: float = 0.8,
) -> List[dict]:
    effect = transition_effect.lower()
    if effect not in SUPPORTED_TRANSITIONS:
        raise ValueError(f"Transition effect must be one of: {', '.join(sorted(SUPPORTED_TRANSITIONS))}.")
    if transition_duration < 0:
        raise ValueError("Transition duration cannot be negative.")
    numeric_durations = [float(duration) for duration in durations]
    if any(duration <= 0 for duration in numeric_durations):
        raise ValueError("All timeline durations must be greater than zero.")

    segments: List[dict] = []
    for index, duration in enumerate(numeric_durations):
        next_transition = 0.0
        if index < len(numeric_durations) - 1 and effect != "none":
            next_transition = min(
                float(transition_duration),
                max(0.0, duration / 2),
                max(0.0, numeric_durations[index + 1] / 2),
            )
        hold_duration = duration
        segments.append({"type": "scene", "scene_index": index, "duration": hold_duration})
        if next_transition > 0:
            segments.append(
                {
                    "type": "transition",
                    "from_scene_index": index,
                    "to_scene_index": index + 1,
                    "duration": next_transition,
                    "effect": effect,
                }
            )
            # The transition is visual-only and consumes time at the boundary. Subtract it
            # from the next static scene so the total timeline remains equal to audio.
            numeric_durations[index + 1] = max(0.05, numeric_durations[index + 1] - next_transition)
    return segments


def export_batch_report(results: Sequence[dict], report_path: str | Path) -> Path:
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "input_pdf",
        "input_audio",
        "output_video",
        "status",
        "error_message",
        "duration",
        "timestamp_csv",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    "input_pdf": str(result.get("pdf_path", "")),
                    "input_audio": str(result.get("audio_path", "")),
                    "output_video": str(result.get("output_path", "")),
                    "status": result.get("status", ""),
                    "error_message": result.get("error") or result.get("error_message", ""),
                    "duration": result.get("duration", ""),
                    "timestamp_csv": str(result.get("detected_csv", "")),
                }
            )
    LOGGER.info("Exported batch report: %s", path)
    return path


def create_video(
    pdf_path: str | Path,
    audio_path: str | Path,
    timestamp_rows: Sequence[dict],
    output_path: str | Path,
    resolution: Tuple[int, int] = (1920, 1080),
    background: str = "white",
    open_book_gap: int = 24,
    render_scale: float = 3.0,
    fps: int = 30,
    keep_temp: bool = False,
    transition_effect: str = "crossfade",
    transition_duration: float = 0.8,
    watermark_options: Optional[dict] = None,
) -> Path:
    pdf = Path(pdf_path)
    audio = Path(audio_path)
    output = Path(output_path)
    if not pdf.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf}")
    if not audio.exists():
        raise FileNotFoundError(f"Audio file not found: {audio}")
    transition_effect = transition_effect.lower()
    if transition_effect not in SUPPORTED_TRANSITIONS:
        raise ValueError(f"Transition effect must be one of: {', '.join(sorted(SUPPORTED_TRANSITIONS))}.")
    if transition_duration < 0:
        raise ValueError("Transition duration cannot be negative.")
    watermark = normalize_watermark_options(**watermark_options) if watermark_options else normalize_watermark_options()
    _check_ffmpeg_available()
    _validate_timestamp_rows(timestamp_rows)

    AudioFileClip, ImageClip, ImageSequenceClip, concatenate_videoclips = _moviepy_imports()
    temp_manager = tempfile.TemporaryDirectory(prefix="flyers_video_")
    work_dir = Path(temp_manager.name)
    output.parent.mkdir(parents=True, exist_ok=True)

    clips = []
    audio_clip = None
    final_clip = None
    try:
        LOGGER.info("Rendering pages...")
        rendered_pages: Dict[int, Path] = {}
        for row in timestamp_rows:
            for page in row["pdf_pages"]:
                if page not in rendered_pages:
                    rendered_pages[page] = render_pdf_page(pdf, page, work_dir / "pages", render_scale)

        LOGGER.info("Creating video scenes...")
        scene_paths: List[Path] = []
        durations: List[float] = []
        for index, row in enumerate(timestamp_rows, start=1):
            pages = row["pdf_pages"]
            raw_scene_path = work_dir / "scenes_raw" / f"scene_{index:02d}.jpg"
            scene_path = work_dir / "scenes" / f"scene_{index:02d}.jpg"
            make_pages_scene(
                [rendered_pages[page] for page in pages],
                raw_scene_path,
                row.get("layout", "auto"),
                resolution,
                background,
                open_book_gap,
            )
            apply_watermark_to_scene(raw_scene_path, scene_path, watermark)
            scene_paths.append(scene_path)
            durations.append(float(row["end_seconds"]) - float(row["start_seconds"]))

        audio_duration = get_audio_duration(audio)
        duration_delta = audio_duration - sum(durations)
        if abs(duration_delta) > 0.01:
            adjusted_last = durations[-1] + duration_delta
            if adjusted_last <= 0.05:
                raise ValueError(
                    "Timestamp duration differs from audio duration too much to adjust safely. "
                    "Review detected_timestamps.csv."
                )
            LOGGER.warning(
                "Adjusting final part duration by %.2fs so video duration matches audio duration.",
                duration_delta,
            )
            durations[-1] = adjusted_last

        LOGGER.info("Creating video...")
        timeline_segments = build_timeline_segments(durations, transition_effect, transition_duration)
        for segment in timeline_segments:
            if segment["type"] == "scene":
                scene_path = scene_paths[segment["scene_index"]]
                clips.append(_clip_with_duration(ImageClip(str(scene_path)), segment["duration"]))
            else:
                frame_paths = _transition_frames(
                    scene_paths[segment["from_scene_index"]],
                    scene_paths[segment["to_scene_index"]],
                    work_dir / "transitions" / f"{segment['from_scene_index']:02d}",
                    segment["effect"],
                    segment["duration"],
                    fps,
                    background,
                )
                if frame_paths:
                    transition_clip = ImageSequenceClip(frame_paths, fps=len(frame_paths) / segment["duration"])
                    clips.append(transition_clip)

        video = concatenate_videoclips(clips, method="compose")
        audio_clip = AudioFileClip(str(audio))
        video_duration = sum(segment["duration"] for segment in timeline_segments)
        audio_for_video = _clip_subclip(audio_clip, 0, min(audio_clip.duration, video_duration))
        final_clip = _clip_with_audio(video, audio_for_video)
        final_clip.write_videofile(
            str(output),
            codec="libx264",
            audio_codec="aac",
            fps=fps,
            preset="medium",
            threads=os.cpu_count() or 4,
        )
    finally:
        for clip in clips:
            close = getattr(clip, "close", None)
            if close:
                close()
        if final_clip is not None and hasattr(final_clip, "close"):
            final_clip.close()
        if audio_clip is not None and hasattr(audio_clip, "close"):
            audio_clip.close()
        if keep_temp:
            LOGGER.info("Keeping temp files at: %s", work_dir)
        else:
            temp_manager.cleanup()

    LOGGER.info("Exported %s", output)
    return output


def detect_timestamps_from_audio(
    audio_path: str | Path,
    test_number: int,
    whisper_model: str,
    language: str,
    level: str = "flyers",
    page_map_config: Optional[dict] = None,
    page_map: Dict[int, Dict[str, List[int]]] = DEFAULT_PAGE_MAP,
) -> Tuple[List[dict], List[str]]:
    audio_duration = get_audio_duration(audio_path)
    segments = transcribe_audio(audio_path, whisper_model=whisper_model, language=language)
    config = page_map_config or get_preset_page_map(level, test_number)
    return detect_part_timestamps(segments, audio_duration, test_number, page_map, config)


def process_batch(
    pairs: Sequence[dict],
    level: str = "flyers",
    test_number: int = 1,
    infer_test_number: bool = True,
    whisper_model: str = "small",
    language: str = "en",
    resolution: Tuple[int, int] = (1920, 1080),
    background: str = "white",
    open_book_gap: int = 24,
    render_scale: float = 3.0,
    transition_effect: str = "crossfade",
    transition_duration: float = 0.8,
    watermark_options: Optional[dict] = None,
    page_map_config: Optional[dict] = None,
    auto_page_map: bool = False,
    ocr_engine: str = "tesseract",
    ocr_language: str = "eng",
    ocr_start_page: int = 1,
    ocr_end_page: Optional[int] = None,
    ocr_render_scale: float = 2.0,
    ocr_min_confidence: float = 55.0,
    detected_csv_dir: Optional[str | Path] = None,
    keep_temp: bool = False,
    csv_only: bool = False,
    overwrite: bool = False,
    batch_report: Optional[str | Path] = None,
    printed_start_page: Optional[int] = None,
) -> List[dict]:
    results: List[dict] = []
    csv_root = Path(detected_csv_dir) if detected_csv_dir else None
    if csv_root:
        csv_root.mkdir(parents=True, exist_ok=True)

    for pair in pairs:
        base_name = pair["base_name"]
        result = dict(pair)
        result["status"] = "processing"
        result["duration"] = ""
        result["detected_csv"] = ""
        try:
            LOGGER.info("[%s] matched", base_name)
            LOGGER.info("[%s] processing", base_name)
            if Path(pair["output_path"]).exists() and not overwrite and not csv_only:
                raise FileExistsError(f"Output exists and --overwrite was not set: {pair['output_path']}")
            active_test_number = pair.get("test_number")
            if active_test_number is None:
                active_test_number = infer_test_number_from_name(base_name, test_number) if infer_test_number else test_number
            active_level = pair.get("level") or level
            active_page_map_config = pair.get("page_map_config") or page_map_config
            if not active_page_map_config and pair.get("page_map_path"):
                active_page_map_config = load_page_map_config(pair["page_map_path"])
            pair_ocr_start = pair.get("ocr_start_page") or ocr_start_page
            pair_ocr_end = pair.get("ocr_end_page") or ocr_end_page
            pair_printed_start = pair.get("printed_start_page") or printed_start_page
            should_auto_page_map = auto_page_map or (
                not active_page_map_config and pair.get("ocr_start_page") and pair.get("ocr_end_page")
            )
            if should_auto_page_map:
                page_map_output_dir = csv_root or Path(pair["output_path"]).parent
                active_page_map_config, page_map_warnings, _ocr_results = auto_detect_page_map_from_pdf(
                    pdf_path=pair["pdf_path"],
                    output_dir=page_map_output_dir,
                    level=active_level,
                    test_number=active_test_number,
                    render_scale=ocr_render_scale,
                    start_page=pair_ocr_start,
                    end_page=pair_ocr_end,
                    ocr_engine=ocr_engine,
                    ocr_language=ocr_language,
                    min_confidence=ocr_min_confidence,
                    printed_start_page=pair_printed_start,
                )
                page_map_json = page_map_output_dir / f"{base_name}_detected_page_map.json"
                export_page_map_config(active_page_map_config, page_map_json)
                result["page_map_json"] = page_map_json
                for warning in page_map_warnings:
                    LOGGER.warning("[%s] Page map warning: %s", base_name, warning)
            audio_duration = get_audio_duration(pair["audio_path"])
            result["duration"] = f"{audio_duration:.3f}"
            rows, warnings = detect_timestamps_from_audio(
                pair["audio_path"],
                active_test_number,
                whisper_model,
                language,
                level=active_level,
                page_map_config=active_page_map_config,
            )
            result["status"] = "timestamp detected"
            result["warnings"] = warnings
            for warning in warnings:
                LOGGER.warning("[%s] Warning: %s", base_name, warning)
            csv_path = (csv_root or Path(pair["output_path"]).parent) / f"{base_name}_detected_timestamps.csv"
            export_detected_timestamps(rows, csv_path)
            result["detected_csv"] = csv_path
            has_invalid_duration = any(float(row["end_seconds"]) <= float(row["start_seconds"]) for row in rows)
            if has_invalid_duration:
                raise ValueError(f"Detected timestamps need manual review: {csv_path}")
            if csv_only:
                LOGGER.info("[%s] csv-only complete: %s", base_name, csv_path)
            else:
                result["status"] = "rendering"
                LOGGER.info("[%s] rendering", base_name)
                create_video(
                    pdf_path=pair["pdf_path"],
                    audio_path=pair["audio_path"],
                    timestamp_rows=rows,
                    output_path=pair["output_path"],
                    resolution=resolution,
                    background=background,
                    open_book_gap=open_book_gap,
                    render_scale=render_scale,
                    keep_temp=keep_temp,
                    transition_effect=transition_effect,
                    transition_duration=transition_duration,
                    watermark_options=watermark_options,
                )
                result["status"] = "exported"
                LOGGER.info("[%s] exported: %s", base_name, pair["output_path"])
        except Exception as exc:
            result["status"] = "failed"
            result["error"] = str(exc)
            LOGGER.error("[%s] failed: %s", base_name, exc)
        results.append(result)
    if batch_report:
        export_batch_report(results, batch_report)
    return results


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create Cambridge Flyers listening videos from PDF + MP3.")
    parser.add_argument("--pdf", help="Input scanned PDF file for single-video mode.")
    parser.add_argument("--audio", help="Input audio file for single-video mode.")
    parser.add_argument("--input-dir", help="Batch mode: folder containing PDF/audio files with matching base filenames.")
    parser.add_argument("--pdfs", nargs="*", help="Batch mode: one or more PDF files.")
    parser.add_argument("--audios", nargs="*", help="Batch mode: one or more audio files.")
    parser.add_argument("--pairing-csv", help="Batch mode: manual pairing CSV. Takes priority over auto matching.")
    parser.add_argument("--output-dir", default="outputs", help="Batch output directory.")
    parser.add_argument("--batch-report", help="Batch report CSV path. Defaults to output-dir/batch_report.csv.")
    parser.add_argument("--level", choices=sorted(SUPPORTED_LEVELS), default="flyers", help="Exam level preset.")
    parser.add_argument("--page-map", help="JSON page map for single-video mode or default batch fallback.")
    parser.add_argument("--auto-page-map", action="store_true", help="Use local OCR to detect page map from PDF.")
    parser.add_argument("--page-map-output", default="detected_page_map.json", help="Output JSON path for auto-detected page map.")
    parser.add_argument("--page-map-only", action="store_true", help="Only detect/export page map JSON, then stop.")
    parser.add_argument("--ocr-engine", default="tesseract", help="Local OCR engine. Currently: tesseract.")
    parser.add_argument("--ocr-language", default="eng", help="OCR language code for Tesseract.")
    parser.add_argument("--ocr-start-page", type=int, default=1, help="First PDF page to OCR for page-map detection.")
    parser.add_argument("--ocr-end-page", type=int, help="Last PDF page to OCR for page-map detection.")
    parser.add_argument("--listening-start-page", type=int, help="Alias for --ocr-start-page.")
    parser.add_argument("--listening-end-page", type=int, help="Alias for --ocr-end-page.")
    parser.add_argument("--printed-start-page", type=int, help="Printed page number of Part 1 for offset calculation.")
    parser.add_argument("--ocr-render-scale", type=float, default=2.0, help="PDF render scale for OCR.")
    parser.add_argument("--ocr-min-confidence", type=float, default=55.0, help="Warn below this average OCR confidence.")
    parser.add_argument("--test", type=int, choices=[1, 2, 3], default=1, help="Test number for default page map.")
    parser.add_argument("--infer-test-from-name", action="store_true", default=True, help="Batch mode: infer Test 1/2/3 from filename.")
    parser.add_argument("--no-infer-test-from-name", dest="infer_test_from_name", action="store_false")
    parser.add_argument("--auto-timestamp", action="store_true", help="Detect part timestamps with local faster-whisper.")
    parser.add_argument("--timestamps", help="Manual or reviewed timestamp CSV.")
    parser.add_argument("--output", help="Output MP4 path for single-video mode.")
    parser.add_argument("--resolution", default="1920x1080", help="Video resolution, e.g. 1920x1080 or 3840x2160.")
    parser.add_argument("--background", default="white", help="'white', 'dark', or CSS color.")
    parser.add_argument("--open-book-gap", type=int, default=24, help="Gap between two-page spreads.")
    parser.add_argument("--render-scale", type=float, default=3.0, help="PyMuPDF render scale.")
    parser.add_argument("--whisper-model", default="small", help="faster-whisper model name or local model path.")
    parser.add_argument("--language", default="en", help="Audio language code for Whisper.")
    parser.add_argument("--detected-csv", default="detected_timestamps.csv", help="CSV path generated by auto timestamp.")
    parser.add_argument("--detected-csv-dir", help="Batch mode: directory for per-file detected timestamp CSVs.")
    parser.add_argument("--csv-only", action="store_true", help="Detect timestamps and write CSV, but do not render video.")
    parser.add_argument("--keep-temp", action="store_true", help="Keep rendered temp images for debugging.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing MP4 outputs.")
    parser.add_argument("--transition-effect", choices=sorted(SUPPORTED_TRANSITIONS), default="crossfade")
    parser.add_argument("--transition-duration", type=float, default=0.8, help="Transition duration in seconds.")
    parser.add_argument("--watermark", action="store_true", help="Enable watermark overlay.")
    parser.add_argument("--watermark-text", help="Text watermark.")
    parser.add_argument("--watermark-image", help="PNG image watermark.")
    parser.add_argument("--watermark-position", choices=sorted(WATERMARK_POSITIONS), default="bottom-right")
    parser.add_argument("--watermark-opacity", type=float, default=0.35)
    parser.add_argument("--watermark-size", type=int, default=120, help="Text font size or PNG max size in pixels.")
    parser.add_argument("--watermark-margin", type=int, default=32)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    configure_logging()
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        resolution = parse_resolution(args.resolution)
        watermark_options = normalize_watermark_options(
            enabled=bool(args.watermark or args.watermark_text or args.watermark_image),
            text=args.watermark_text,
            image=args.watermark_image,
            position=args.watermark_position,
            opacity=args.watermark_opacity,
            size=args.watermark_size,
            margin=args.watermark_margin,
        )
        ocr_start_page = args.listening_start_page or args.ocr_start_page
        ocr_end_page = args.listening_end_page or args.ocr_end_page
        batch_mode = bool(args.pairing_csv or args.input_dir or args.pdfs or args.audios)
        cli_page_map_config = load_page_map_config(args.page_map) if args.page_map else None
        if batch_mode:
            if args.pairing_csv:
                pairs = read_pairing_csv(args.pairing_csv, output_dir=args.output_dir)
                warnings = []
            else:
                pairs, warnings = discover_batch_pairs(
                    input_dir=args.input_dir,
                    pdfs=args.pdfs,
                    audios=args.audios,
                    output_dir=args.output_dir,
                )
            for warning in warnings:
                LOGGER.warning("Warning: %s", warning)
            report_path = Path(args.batch_report) if args.batch_report else Path(args.output_dir) / "batch_report.csv"
            if not pairs:
                LOGGER.error("No matched PDF/audio pairs found.")
                export_batch_report([], report_path)
                return 1
            results = process_batch(
                pairs,
                level=args.level,
                test_number=args.test,
                infer_test_number=args.infer_test_from_name,
                whisper_model=args.whisper_model,
                language=args.language,
                resolution=resolution,
                background=args.background,
                open_book_gap=args.open_book_gap,
                render_scale=args.render_scale,
                transition_effect=args.transition_effect,
                transition_duration=args.transition_duration,
                watermark_options=watermark_options,
                page_map_config=cli_page_map_config,
                auto_page_map=args.auto_page_map,
                ocr_engine=args.ocr_engine,
                ocr_language=args.ocr_language,
                ocr_start_page=ocr_start_page,
                ocr_end_page=ocr_end_page,
                ocr_render_scale=args.ocr_render_scale,
                ocr_min_confidence=args.ocr_min_confidence,
                detected_csv_dir=args.detected_csv_dir,
                keep_temp=args.keep_temp,
                csv_only=args.csv_only,
                overwrite=args.overwrite,
                batch_report=report_path,
                printed_start_page=args.printed_start_page,
            )
            failed = [result for result in results if result.get("status") == "failed"]
            LOGGER.info("Batch finished: %s exported, %s failed.", len(results) - len(failed), len(failed))
            return 1 if failed else 0

        if args.page_map_only and args.auto_page_map:
            if not args.pdf:
                parser.error("--page-map-only with --auto-page-map requires --pdf.")
        elif not args.pdf or not args.audio or not args.output:
            parser.error("Single-video mode requires --pdf, --audio, and --output.")
        if args.output and Path(args.output).exists() and not args.overwrite and not args.csv_only:
            raise FileExistsError(f"Output exists and --overwrite was not set: {args.output}")
        if args.auto_page_map:
            output_parent = Path(args.page_map_output).parent
            if str(output_parent) in ("", "."):
                output_parent = Path.cwd()
            cli_page_map_config, page_map_warnings, _ocr_results = auto_detect_page_map_from_pdf(
                pdf_path=args.pdf,
                output_dir=output_parent,
                level=args.level,
                test_number=args.test,
                render_scale=args.ocr_render_scale,
                start_page=ocr_start_page,
                end_page=ocr_end_page,
                ocr_engine=args.ocr_engine,
                ocr_language=args.ocr_language,
                min_confidence=args.ocr_min_confidence,
                printed_start_page=args.printed_start_page,
            )
            export_page_map_config(cli_page_map_config, args.page_map_output)
            for warning in page_map_warnings:
                LOGGER.warning("Page map warning: %s", warning)
            if args.page_map_only:
                return 0
        if args.timestamps:
            timestamp_rows = parse_timestamps_csv(args.timestamps)
        elif args.auto_timestamp:
            timestamp_rows, warnings = detect_timestamps_from_audio(
                args.audio,
                args.test,
                args.whisper_model,
                args.language,
                level=args.level,
                page_map_config=cli_page_map_config,
            )
            export_detected_timestamps(timestamp_rows, args.detected_csv)
            for warning in warnings:
                LOGGER.warning("Warning: %s", warning)
            has_invalid_duration = any(
                float(row["end_seconds"]) <= float(row["start_seconds"]) for row in timestamp_rows
            )
            if args.csv_only:
                return 0
            if has_invalid_duration:
                LOGGER.error(
                    "Detected timestamps need manual review. Edit %s and rerun with --timestamps.",
                    args.detected_csv,
                )
                return 1
        else:
            parser.error("Use --auto-timestamp or provide --timestamps detected_timestamps.csv.")

        create_video(
            pdf_path=args.pdf,
            audio_path=args.audio,
            timestamp_rows=timestamp_rows,
            output_path=args.output,
            resolution=resolution,
            background=args.background,
            open_book_gap=args.open_book_gap,
            render_scale=args.render_scale,
            keep_temp=args.keep_temp,
            transition_effect=args.transition_effect,
            transition_duration=args.transition_duration,
            watermark_options=watermark_options,
        )
        return 0
    except Exception as exc:
        LOGGER.error("Error: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
