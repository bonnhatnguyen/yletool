from flyers_video_tool.flyers_video_tool import build_page_map_from_ocr_results

def test_flyers_1_regression():
    mock_ocr = [
        # Page 4: Contents page containing "Listening" and "Reading and Writing"
        {"page": 4, "text": "Contents\nTest 1 Listening\nTest 1 Reading and Writing\nTest 2 Listening\n", "heading_text": "Contents"},
        # Page 5: Part 1 start
        {"page": 5, "text": "Listen and draw lines. There is one example.", "heading_text": "Test 1 Listening Part 1"},
        # Page 6: Part 2 start
        {"page": 6, "text": "Listen and write. There is one example.", "heading_text": "Part 2"},
        # Page 7: Part 3 start
        {"page": 7, "text": "What did they do? Listen and draw a line.", "heading_text": "Part 3"},
        # Page 8: Part 3 continuation
        {"page": 8, "text": "Some more questions for Part 3.", "heading_text": ""},
        # Page 9: Part 4 start
        {"page": 9, "text": "Listen and tick the box.", "heading_text": "Part 4"},
        # Page 10: Part 4 continuation
        {"page": 10, "text": "Some more questions for Part 4.", "heading_text": ""},
        # Page 11: Part 5 start
        {"page": 11, "text": "Listen and colour and draw.", "heading_text": "Part 5"},
        # Page 12: Reading and Writing start (this should trigger stop)
        {"page": 12, "text": "Look and read. Choose the correct words.", "heading_text": "Test 1 Reading and Writing Part 1"},
    ]
    
    config, warnings = build_page_map_from_ocr_results(
        mock_ocr,
        level="flyers",
        test_number=1,
        printed_start_page=4,
    )
    
    print("Detected config:", config)
    print("Warnings:", warnings)
    
    assert config["pdf_offset"] == 1
    parts = config["parts"]
    assert len(parts) == 5
    
    assert parts[0]["part"] == 1 and parts[0]["pages"] == [5]
    assert parts[1]["part"] == 2 and parts[1]["pages"] == [6]
    assert parts[2]["part"] == 3 and parts[2]["pages"] == [7, 8]
    assert parts[3]["part"] == 4 and parts[3]["pages"] == [9, 10]
    assert parts[4]["part"] == 5 and parts[4]["pages"] == [11]
    
    # Check printed pages correctly calculated
    assert parts[0]["printed_pages"] == [4]
    assert parts[4]["printed_pages"] == [10]

if __name__ == "__main__":
    test_flyers_1_regression()
    print("Test passed successfully!")
