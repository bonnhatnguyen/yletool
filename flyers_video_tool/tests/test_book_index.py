import pytest
from pathlib import Path
from flyers_video_tool.flyers_video_tool import build_book_index_from_pdf, infer_test_number_from_name, BOOK_INDEX_CACHE_VERSION

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

def test_infer_test_number_from_name():
    assert infer_test_number_from_name("Flyers Test 4.mp3") == 4
    assert infer_test_number_from_name("Movers TEST 12 Listening") == 12
    assert infer_test_number_from_name("Random Audio.mp3") == 1

def test_build_book_index_hybrid_and_backward_search(monkeypatch, tmp_path):
    # Mock compute_file_hash to return a fixed string
    monkeypatch.setattr("flyers_video_tool.flyers_video_tool.compute_file_hash", lambda x: "dummy_hash")
    
    # We will simulate a document with 50 pages.
    # Pages 1-22: Random stuff
    # Page 23: Text layer is EMPTY (simulating image-heavy page). OCR will find "Test 2 Listening Part 1"
    # Page 24: "Test 2 Part 2"
    # Page 27: "Test 2 Part 4"
    # Page 29: "Test 2 Part 5"
    # Page 41: Text layer EMPTY. OCR will find "Test 3 Listening Part 1"
    # Page 47: "Test 3 Part 5"
    
    pages = [MockFitzPage("Random stuff")] * 50
    pages[22] = MockFitzPage(" ") # Page 23 sparse
    pages[23] = MockFitzPage("Test 2 Part 2")
    pages[26] = MockFitzPage("Test 2 Part 4")
    pages[28] = MockFitzPage("Test 2 Part 5")
    
    pages[40] = MockFitzPage(" ") # Page 41 sparse
    pages[46] = MockFitzPage("Test 3 Part 5")

    monkeypatch.setattr("flyers_video_tool.flyers_video_tool.fitz", type("obj", (object,), {"open": lambda p: MockFitzDoc(pages)}))
    
    def mock_ocr_pdf_pages(pdf_path, output_dir, start_page, end_page, **kwargs):
        if start_page == 23:
            return [{"page": 23, "text": "Test 2 Listening Part 1", "heading_text": "Test 2 Listening Part 1", "confidence": 95.0}]
        if start_page == 41:
            return [{"page": 41, "text": "Test 3 Listening Part 1", "heading_text": "Test 3 Listening Part 1", "confidence": 95.0}]
        return [{"page": start_page, "text": "", "heading_text": "", "confidence": 0.0}]
        
    monkeypatch.setattr("flyers_video_tool.flyers_video_tool.ocr_pdf_pages", mock_ocr_pdf_pages)
    
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
    assert t2["start_page"] == 23 # OCR fallback found it at 23
    
    t3 = tests[1]
    assert t3["test"] == 3
    assert t3["start_page"] == 41 # OCR fallback found it at 41

def test_backward_search(monkeypatch, tmp_path):
    monkeypatch.setattr("flyers_video_tool.flyers_video_tool.compute_file_hash", lambda x: "dummy_hash_backward")
    
    def mock_extract(pdf_path, use_ocr_fallback, progress_callback, log_callback, output_dir):
        pages = []
        for i in range(1, 10):
            pages.append({"page": i, "normalized_merged": "random", "normalized_heading": "random"})
        
        pages.extend([
            {"page": 10, "normalized_merged": "test 4 listening part 1", "normalized_heading": "test 4 listening part 1"},
            {"page": 11, "normalized_merged": "random", "normalized_heading": "random"},
            {"page": 12, "normalized_merged": "random", "normalized_heading": "random"},
            {"page": 13, "normalized_merged": "random", "normalized_heading": "random"},
            {"page": 14, "normalized_merged": "test 4", "normalized_heading": "test 4"}, 
            {"page": 15, "normalized_merged": "part 4", "normalized_heading": "part 4"},
            {"page": 16, "normalized_merged": "part 5", "normalized_heading": "part 5"},
            {"page": 17, "normalized_merged": "reading and writing", "normalized_heading": "reading and writing"}
        ])
        return pages
        
    monkeypatch.setattr("flyers_video_tool.flyers_video_tool.extract_pdf_text_index", mock_extract)
    
    index, warnings = build_book_index_from_pdf(
        pdf_path="dummy.pdf",
        output_dir=tmp_path,
        level="flyers",
        use_ocr_fallback=False
    )
    
    tests = index["tests"]
    assert len(tests) == 1
    t4 = tests[0]
    
    assert t4["test"] == 4
    assert t4["start_page"] == 10
    
    parts = t4["parts"]
    assert any(p["part"] == 1 for p in parts)
    assert any(p["part"] == 4 for p in parts)
    assert any(p["part"] == 5 for p in parts)
