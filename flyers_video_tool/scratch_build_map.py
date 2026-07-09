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
    return result_config, warnings
