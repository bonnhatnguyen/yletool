import pytest
from pathlib import Path
from flyers_video_tool.flyers_video_tool import (
    build_book_index_from_pdf, 
    infer_test_number_from_name, 
    BOOK_INDEX_CACHE_VERSION,
    detect_test_number_robust,
    detect_part_number_robust
)

class MockFitzPage:
    def __init__(self, text):
        self.text = text
    def get_text(self):
        return self.text

class MockFitzDoc:
    def __init__(self, pages):
        self.pages = pages
    def __len__(self):
        return len(self.pages)
    def __getitem__(self, idx):
        return self.pages[idx]
    def close(self):
        pass

def test_robust_detectors():
    assert detect_part_number_robust("Part I") == 1
    assert detect_part_number_robust("Part l") == 1
    assert detect_part_number_robust("part one") == 1
    assert detect_part_number_robust("p art 1") == 1
    assert detect_part_number_robust("practlce part 3") == 3
    assert detect_part_number_robust("random text") == None
    
    assert detect_test_number_robust("t e s t 2") == 2
    assert detect_test_number_robust("Practice Test 8") == 8
    assert detect_test_number_robust("test two") == 2
    assert detect_test_number_robust("practlce test 1") == 1

def test_infer_test_number_from_name():
    assert infer_test_number_from_name("Flyers Test 4.mp3") == 4
    assert infer_test_number_from_name("Movers TEST 12 Listening") == 12
    assert infer_test_number_from_name("Random Audio.mp3") == 1

def test_build_book_index_hybrid_and_backward_search(monkeypatch, tmp_path):
    monkeypatch.setattr("flyers_video_tool.flyers_video_tool.compute_file_hash", lambda x: "dummy_hash")
    
    pages = [MockFitzPage("Random stuff")] * 50
    pages[22] = MockFitzPage(" ") 
    pages[23] = MockFitzPage("Test 2 Part 2")
    pages[26] = MockFitzPage("Test 2 Part 4")
    pages[28] = MockFitzPage("Test 2 Part 5")
    
    pages[40] = MockFitzPage(" ") 
    pages[46] = MockFitzPage("Test 3 Part 5")

    monkeypatch.setattr("flyers_video_tool.flyers_video_tool.fitz", type("obj", (object,), {"open": lambda p: MockFitzDoc(pages)}))
    
    def mock_extract(pdf_path, use_ocr_fallback, progress_callback, log_callback, output_dir):
        res = []
        for i in range(1, 51):
            t = "random"
            if i == 23: t = "test 2 listening part 1"
            elif i == 24: t = "test 2 part 2"
            elif i == 27: t = "test 2 part 4"
            elif i == 29: t = "test 2 part 5"
            elif i == 41: t = "test 3 listening part 1"
            elif i == 47: t = "test 3 part 5"
            
            res.append({
                "page": i,
                "text_source": "hybrid",
                "robust_test": detect_test_number_robust(t),
                "robust_part": detect_part_number_robust(t),
                "merged_text": t,
                "merged_heading": t,
                "normalized_merged": t,
                "normalized_heading": t,
                "ocr_heading_top35": t,
                "ocr_heading_top50": t
            })
        return res
        
    monkeypatch.setattr("flyers_video_tool.flyers_video_tool.extract_pdf_text_index", mock_extract)
    
    index, warnings = build_book_index_from_pdf(
        pdf_path="dummy.pdf",
        output_dir=tmp_path,
        level="flyers",
        use_ocr_fallback=True
    )
    
    tests = index["tests"]
    assert len(tests) == 2
    
    t2 = tests[0]
    assert t2["test"] == 2
    assert t2["start_page"] == 23 
    
    t3 = tests[1]
    assert t3["test"] == 3
    assert t3["start_page"] == 41

def test_succeed_format_with_cover_page(monkeypatch, tmp_path):
    monkeypatch.setattr("flyers_video_tool.flyers_video_tool.compute_file_hash", lambda x: "dummy_hash_succeed")
    
    def mock_extract(pdf_path, use_ocr_fallback, progress_callback, log_callback, output_dir):
        res = []
        # Add contents pages
        res.append({
            "page": 1,
            "robust_test": None, "robust_part": None,
            "merged_text": "Contents Practice Test 1 Page 5 Practice Test 2 Page 31 Practice Test 3 Page 57 Practice Test 4 Page 83 Practice Test 5 Page 109 Practice Test 6 Page 135 Practice Test 7 Page 161 Practice Test 8 Page 187",
            "merged_heading": "Contents"
        })
        for i in range(2, 6):
            res.append({"page": i, "robust_test": None, "robust_part": None, "merged_text": "", "merged_heading": ""})
            
        # Page 6: Practice Test 1 Cover page
        res.append({
            "page": 6, "robust_test": 1, "robust_part": None, 
            "merged_text": "Practice Test 1", "merged_heading": "Practice Test 1"
        })
        # Page 7: Part 1
        res.append({
            "page": 7, "robust_test": 1, "robust_part": 1,
            "merged_text": "Listening Part 1", "merged_heading": "Listening Part 1"
        })
        return res
        
    monkeypatch.setattr("flyers_video_tool.flyers_video_tool.extract_pdf_text_index", mock_extract)
    
    index, warnings = build_book_index_from_pdf(
        pdf_path="dummy.pdf",
        output_dir=tmp_path,
        level="flyers",
        use_ocr_fallback=False
    )
    
    assert index["format"] == "succeed_flyers_8_tests"
    assert index["estimated_pdf_offset"] == 1 # printed page 5 is pdf page 6
    tests = index["tests"]
    assert len(tests) == 1
    t1 = tests[0]
    assert t1["test"] == 1
    assert t1["cover_page"] == 6
    assert t1["start_page"] == 7

def test_structural_inference(monkeypatch, tmp_path):
    monkeypatch.setattr("flyers_video_tool.flyers_video_tool.compute_file_hash", lambda x: "dummy_hash_inference")
    
    def mock_extract(pdf_path, use_ocr_fallback, progress_callback, log_callback, output_dir):
        res = []
        for i in range(1, 30):
            t = ""
            # Simulate Test 2 missing early parts.
            if i == 23: t = "random" # Should be Part 1
            elif i == 24: t = "random" # Should be Part 2
            elif i == 25: t = "random" # Should be Part 3
            elif i == 27: t = "Test 2 Part 4" # We found Part 4
            elif i == 29: t = "Test 2 Part 5" # We found Part 5
            
            res.append({
                "page": i,
                "text_source": "hybrid",
                "robust_test": detect_test_number_robust(t),
                "robust_part": detect_part_number_robust(t),
                "merged_text": t,
                "merged_heading": t,
                "normalized_merged": t,
                "normalized_heading": t
            })
        return res
        
    monkeypatch.setattr("flyers_video_tool.flyers_video_tool.extract_pdf_text_index", mock_extract)
    
    index, warnings = build_book_index_from_pdf(
        pdf_path="dummy.pdf",
        output_dir=tmp_path,
        level="flyers",
        use_ocr_fallback=False
    )
    
    tests = index["tests"]
    assert len(tests) == 1
    t2 = tests[0]
    
    assert t2["test"] == 2
    assert t2["start_page"] == 23 # Initially detected at 27
    
    parts = t2["parts"]
    assert len(parts) == 5
    assert t2["status"] == "Review"
    assert any("inferred from YLE layout" in w for w in t2["warnings"])
    
    # Verify inferred pages based on Flyers layout [1, 1, 2, 2, 1]
    # Part 4 starts at 27. Part 3 should be 27-2 = 25. Part 2 should be 25-1 = 24. Part 1 should be 24-1 = 23.
    p1 = next(p for p in parts if p["part"] == 1)
    assert p1["pages"] == [23]
    p2 = next(p for p in parts if p["part"] == 2)
    assert p2["pages"] == [24]
    p3 = next(p for p in parts if p["part"] == 3)
    assert p3["pages"] == [25, 26] # part 3 is 2 pages long because part 4 starts at 27
