import csv
import json
import tempfile
import unittest
from pathlib import Path

from flyers_video_tool import (
    DEFAULT_PAGE_MAP,
    build_page_map_from_ocr_results,
    detect_part_timestamps,
    discover_batch_pairs,
    export_batch_report,
    export_detected_timestamps,
    format_timestamp,
    get_preset_page_map,
    load_page_map_config,
    normalize_watermark_options,
    parse_timestamp,
    parse_timestamps_csv,
    read_pairing_csv,
)


class TimestampHelpersTest(unittest.TestCase):
    def test_parse_and_format_timestamp(self):
        self.assertEqual(parse_timestamp("05:40"), 340.0)
        self.assertEqual(parse_timestamp("01:02:03"), 3723.0)
        self.assertEqual(format_timestamp(340.4), "05:40")
        self.assertEqual(format_timestamp(3723.0), "01:02:03")


class DetectPartTimestampsTest(unittest.TestCase):
    def test_detects_ordered_part_starts_from_segments(self):
        segments = [
            {"start": 0.0, "end": 3.0, "text": "Cambridge Flyers listening test"},
            {"start": 4.2, "end": 7.0, "text": "Now listen to part one."},
            {"start": 301.0, "end": 305.0, "text": "Look at part two."},
            {"start": 700.0, "end": 704.0, "text": "Part three. Listen and draw lines."},
            {"start": 1000.0, "end": 1003.0, "text": "Now listen to part four."},
            {"start": 1300.0, "end": 1305.0, "text": "Now listen to part five."},
        ]

        rows, warnings = detect_part_timestamps(
            segments=segments,
            audio_duration=1600.0,
            test_number=1,
            page_map=DEFAULT_PAGE_MAP,
        )

        self.assertEqual(warnings, [])
        self.assertEqual([row["start_seconds"] for row in rows], [4.2, 301.0, 700.0, 1000.0, 1300.0])
        self.assertEqual(rows[-1]["end_seconds"], 1600.0)
        self.assertEqual(rows[2]["pdf_pages"], [7, 8])

    def test_missing_part_uses_previous_end_and_reports_warning(self):
        segments = [
            {"start": 10.0, "end": 12.0, "text": "part one"},
            {"start": 300.0, "end": 302.0, "text": "part two"},
            {"start": 900.0, "end": 902.0, "text": "part four"},
            {"start": 1200.0, "end": 1202.0, "text": "part five"},
        ]

        rows, warnings = detect_part_timestamps(
            segments=segments,
            audio_duration=1500.0,
            test_number=1,
            page_map=DEFAULT_PAGE_MAP,
        )

        self.assertIn("Part 3", warnings[0])
        self.assertEqual(rows[2]["title"], "Part 3")
        self.assertEqual(rows[2]["start_seconds"], rows[1]["end_seconds"])

    def test_dynamic_page_map_detects_only_configured_parts(self):
        page_map = {
            "level": "starters",
            "test": 1,
            "parts": [
                {"part": 1, "title": "Part 1", "pages": [5], "layout": "single"},
                {"part": 2, "title": "Part 2", "pages": [6], "layout": "single"},
                {"part": 3, "title": "Part 3", "pages": [7, 8], "layout": "side_by_side"},
                {"part": 4, "title": "Part 4", "pages": [9], "layout": "single"},
            ],
        }
        segments = [
            {"start": 1.0, "end": 2.0, "text": "part one"},
            {"start": 100.0, "end": 101.0, "text": "part two"},
            {"start": 200.0, "end": 201.0, "text": "part three"},
            {"start": 300.0, "end": 301.0, "text": "part four"},
            {"start": 400.0, "end": 401.0, "text": "part five"},
        ]

        rows, warnings = detect_part_timestamps(
            segments=segments,
            audio_duration=500.0,
            page_map_config=page_map,
        )

        self.assertEqual(warnings, [])
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[-1]["title"], "Part 4")
        self.assertEqual(rows[2]["layout"], "side_by_side")


class CsvRoundTripTest(unittest.TestCase):
    def test_export_and_parse_timestamps_csv(self):
        rows = [
            {
                "title": "Part 1",
                "start_seconds": 0.0,
                "end_seconds": 340.0,
                "pdf_pages": [5],
                "layout": "single",
            },
            {
                "title": "Part 3",
                "start_seconds": 700.0,
                "end_seconds": 1000.0,
                "pdf_pages": [7, 8],
                "layout": "side_by_side",
            },
        ]

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timestamps.csv"
            export_detected_timestamps(rows, path)
            parsed = parse_timestamps_csv(path)

        self.assertEqual(parsed[0]["title"], "Part 1")
        self.assertEqual(parsed[0]["start_seconds"], 0.0)
        self.assertEqual(parsed[1]["pdf_pages"], [7, 8])
        self.assertEqual(parsed[1]["layout"], "side_by_side")

    def test_parse_csv_rejects_invalid_ranges(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["title", "start", "end", "pdf_pages"])
                writer.writerow(["Part 1", "05:00", "04:00", "5"])

            with self.assertRaises(ValueError):
                parse_timestamps_csv(path)


class BatchMatchingTest(unittest.TestCase):
    def test_matches_pdf_and_audio_by_same_base_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Flyers 1 Test 1.pdf").write_bytes(b"%PDF")
            (root / "Flyers 1 Test 1.mp3").write_bytes(b"audio")
            (root / "Flyers 1 Test 2.pdf").write_bytes(b"%PDF")
            (root / "Flyers 1 Test 2.mp3").write_bytes(b"audio")

            pairs, warnings = discover_batch_pairs(input_dir=root, output_dir=root / "out")

        self.assertEqual(warnings, [])
        self.assertEqual([pair["base_name"] for pair in pairs], ["Flyers 1 Test 1", "Flyers 1 Test 2"])
        self.assertEqual(pairs[0]["output_path"].name, "Flyers 1 Test 1.mp4")

    def test_skips_unmatched_files_and_reports_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Only PDF.pdf").write_bytes(b"%PDF")
            (root / "Only Audio.mp3").write_bytes(b"audio")
            (root / "Matched.pdf").write_bytes(b"%PDF")
            (root / "Matched.mp3").write_bytes(b"audio")

            pairs, warnings = discover_batch_pairs(input_dir=root, output_dir=root / "out")

        self.assertEqual([pair["base_name"] for pair in pairs], ["Matched"])
        self.assertEqual(len(warnings), 2)
        self.assertTrue(any("Missing MP3" in warning for warning in warnings))
        self.assertTrue(any("Missing PDF" in warning for warning in warnings))

    def test_reads_manual_pairing_csv_instead_of_auto_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "book.pdf").write_bytes(b"%PDF")
            (root / "audio.mp3").write_bytes(b"audio")
            pairing = root / "pairing.csv"
            with pairing.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["pdf", "audio", "output_name", "test"])
                writer.writerow(["book.pdf", "audio.mp3", "Custom Output", "2"])

            pairs = read_pairing_csv(pairing, output_dir=root / "out")

        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["base_name"], "Custom Output")
        self.assertEqual(pairs[0]["test_number"], 2)
        self.assertEqual(pairs[0]["output_path"].name, "Custom Output.mp4")

    def test_pairing_csv_supports_level_and_page_map_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "book.pdf").write_bytes(b"%PDF")
            (root / "audio.mp3").write_bytes(b"audio")
            page_map = root / "page_map.json"
            page_map.write_text(
                json.dumps(
                    {
                        "level": "starters",
                        "test": 1,
                        "parts": [
                            {"part": 1, "title": "Part 1", "pages": [5], "layout": "single"},
                            {"part": 2, "title": "Part 2", "pages": [6], "layout": "single"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            pairing = root / "pairing.csv"
            with pairing.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["pdf", "audio", "output_name", "level", "test", "page_map"])
                writer.writerow(["book.pdf", "audio.mp3", "Starter Output", "starters", "1", "page_map.json"])

            pairs = read_pairing_csv(pairing, output_dir=root / "out")

        self.assertEqual(pairs[0]["level"], "starters")
        self.assertEqual(pairs[0]["page_map_path"].name, "page_map.json")
        self.assertEqual(len(pairs[0]["page_map_config"]["parts"]), 2)

    def test_pairing_csv_supports_ocr_page_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "book.pdf").write_bytes(b"%PDF")
            (root / "audio.mp3").write_bytes(b"audio")
            pairing = root / "pairing.csv"
            with pairing.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["pdf", "audio", "output_name", "level", "test", "page_map", "ocr_start_page", "ocr_end_page"])
                writer.writerow(["book.pdf", "audio.mp3", "OCR Range", "flyers", "1", "", "5", "12"])

            pairs = read_pairing_csv(pairing, output_dir=root / "out")

        self.assertEqual(pairs[0]["ocr_start_page"], 5)
        self.assertEqual(pairs[0]["ocr_end_page"], 12)


class PageMapConfigTest(unittest.TestCase):
    def test_loads_page_map_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "page_map.json"
            path.write_text(
                json.dumps(
                    {
                        "level": "starters",
                        "test": 1,
                        "parts": [
                            {"part": 1, "title": "Part 1", "pages": [5], "layout": "single"},
                            {"part": 2, "title": "Part 2", "pages": [6, 7, 8], "layout": "grid"},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            config = load_page_map_config(path)

        self.assertEqual(config["level"], "starters")
        self.assertEqual(len(config["parts"]), 2)
        self.assertEqual(config["parts"][1]["layout"], "grid")

    def test_preset_uses_level_and_test(self):
        config = get_preset_page_map("flyers", 1)

        self.assertEqual(config["level"], "flyers")
        self.assertEqual(len(config["parts"]), 5)


class AutoPageMapTest(unittest.TestCase):
    def test_builds_dynamic_page_map_from_ocr_headings(self):
        ocr_results = [
            {"page": 5, "text": "Test 1 Listening Part 1 Look and listen", "confidence": 91},
            {"page": 6, "text": "Part two Read the question", "confidence": 89},
            {"page": 7, "text": "Part 3 Listen and draw lines", "confidence": 93},
            {"page": 8, "text": "More questions for part 3", "confidence": 82},
            {"page": 9, "text": "Part four Listen and colour", "confidence": 88},
            {"page": 10, "text": "Answer key", "confidence": 95},
        ]

        config, warnings = build_page_map_from_ocr_results(ocr_results, level="starters", test_number=1)

        self.assertEqual(warnings, [])
        self.assertEqual(len(config["parts"]), 4)
        self.assertEqual(config["parts"][0]["pages"], [5])
        self.assertEqual(config["parts"][2]["pages"], [7, 8])
        self.assertEqual(config["parts"][2]["layout"], "side_by_side")
        self.assertEqual(config["parts"][3]["pages"], [9])

    def test_auto_page_map_warns_about_missing_part_gap_and_low_confidence(self):
        ocr_results = [
            {"page": 1, "text": "Test 1 Listening Part 1", "confidence": 91},
            {"page": 5, "text": "Part 3", "confidence": 41},
            {"page": 7, "text": "Transcript", "confidence": 90},
        ]

        config, warnings = build_page_map_from_ocr_results(ocr_results, level="starters", test_number=1)

        self.assertEqual([part["part"] for part in config["parts"]], [1, 3])
        self.assertTrue(any("Missing heading for Part 2" in warning for warning in warnings))
        self.assertTrue(any("low OCR confidence" in warning for warning in warnings))

    def test_auto_page_map_uses_increasing_part_sequence_when_duplicates_exist(self):
        ocr_results = [
            {"page": 5, "heading_text": "Listening Part 1 Questions 1-5", "text": "Part 1", "confidence": 92},
            {"page": 6, "heading_text": "Part 2 Questions", "text": "Part 2", "confidence": 90},
            {"page": 7, "heading_text": "Part 3", "text": "Part 3", "confidence": 90},
            {"page": 8, "heading_text": "Reading and Writing Part 1", "text": "Part 1", "confidence": 90},
            {"page": 9, "heading_text": "Part 4", "text": "Part four", "confidence": 90},
            {"page": 10, "heading_text": "Transcript Part 1", "text": "Transcript Part 1", "confidence": 90},
        ]

        config, warnings = build_page_map_from_ocr_results(
            ocr_results,
            level="starters",
            test_number=1,
            start_page=5,
            max_page=9,
        )

        self.assertEqual([part["part"] for part in config["parts"]], [1, 2, 3, 4])
        self.assertEqual(config["parts"][2]["pages"], [7, 8])
        self.assertFalse(any("Part 1 at page 8" in warning for warning in warnings))


class BatchReportTest(unittest.TestCase):
    def test_exports_batch_report_with_required_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "batch_report.csv"
            results = [
                {
                    "pdf_path": Path(tmp) / "a.pdf",
                    "audio_path": Path(tmp) / "a.mp3",
                    "output_path": Path(tmp) / "a.mp4",
                    "status": "failed",
                    "error": "bad timestamp",
                    "duration": 123.4,
                    "detected_csv": Path(tmp) / "a_detected_timestamps.csv",
                }
            ]

            export_batch_report(results, path)
            with path.open("r", newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(rows[0]["input_pdf"], str(Path(tmp) / "a.pdf"))
        self.assertEqual(rows[0]["status"], "failed")
        self.assertEqual(rows[0]["error_message"], "bad timestamp")


class WatermarkOptionsTest(unittest.TestCase):
    def test_normalizes_disabled_watermark(self):
        options = normalize_watermark_options(enabled=False, text="Brand")
        self.assertFalse(options["enabled"])
        self.assertIsNone(options["text"])

    def test_rejects_invalid_watermark_position(self):
        with self.assertRaises(ValueError):
            normalize_watermark_options(enabled=True, text="Brand", position="middle-right")


class NormalizeResolutionTest(unittest.TestCase):
    def test_normalize_resolution_string(self):
        from flyers_video_tool.flyers_video_tool import normalize_resolution
        self.assertEqual(normalize_resolution("1280x720"), (1280, 720))
        self.assertEqual(normalize_resolution(" 1920 X 1080 "), (1920, 1080))

    def test_normalize_resolution_tuple(self):
        from flyers_video_tool.flyers_video_tool import normalize_resolution
        self.assertEqual(normalize_resolution((1280, 720)), (1280, 720))
        self.assertEqual(normalize_resolution([3840, 2160]), (3840, 2160))
        
    def test_normalize_resolution_invalid(self):
        from flyers_video_tool.flyers_video_tool import normalize_resolution
        with self.assertRaisesRegex(ValueError, "Invalid resolution"):
            normalize_resolution("1280")
        with self.assertRaisesRegex(ValueError, "Invalid resolution"):
            normalize_resolution((1280,))


if __name__ == "__main__":
    unittest.main()
