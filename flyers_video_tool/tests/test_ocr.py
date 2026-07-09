import pytest
from flyers_video_tool.flyers_video_tool import build_page_map_from_ocr_results

def test_ocr_regression_contents_and_stop_page():
    # Simulate OCR results that have a Contents page and a Reading & Writing stop page
    ocr_results = [
        {"page": 1, "text": "Cambridge English Flyers\nStudent's Book", "confidence": 99},
        {"page": 2, "text": "Contents\nTest 1 Listening 4\nTest 2 Listening 12", "confidence": 99},
        {"page": 3, "text": "some blank page", "confidence": 99},
        {"page": 4, "text": "Test 1\nListening\nPart 1\nListen and draw lines", "confidence": 99},
        {"page": 5, "text": "Part 2\nListen and write", "confidence": 99},
        {"page": 6, "text": "Part 3\nWhat did they do?", "confidence": 99},
        {"page": 7, "text": "Part 4\nListen and tick the box", "confidence": 99},
        {"page": 8, "text": "Part 5\nListen and colour", "confidence": 99},
        {"page": 9, "text": "Test 1\nReading and Writing\nPart 1", "confidence": 99}
    ]
    
    # We want to test if it builds correct pages and ignores Reading and Writing
    page_map, warnings = build_page_map_from_ocr_results(ocr_results, level="flyers", test_number=1)
    
    assert page_map is not None
    
    parts = page_map["parts"]
    assert len(parts) == 5
    
    # Check that pages for Part 5 stops before Reading and Writing (page 9)
    assert 9 not in parts[4]["pages"]
    assert parts[4]["pages"] == [8]

    # Parts pages
    assert parts[0]["pages"] == [4]
    assert parts[1]["pages"] == [5]
    assert parts[2]["pages"] == [6]
    assert parts[3]["pages"] == [7]
