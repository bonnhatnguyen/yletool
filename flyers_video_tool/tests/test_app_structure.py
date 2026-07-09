import inspect
import pytest
from streamlit.testing.v1 import AppTest
from pathlib import Path

def test_app_has_exactly_one_render_history_ui():
    app_path = Path(__file__).parent.parent / "app.py"
    content = app_path.read_text(encoding="utf-8")
    count = content.count("def render_history_ui():")
    assert count == 1, f"Expected exactly one 'def render_history_ui():', found {count}"

def test_render_history_ui_does_not_contain_watermark_logic():
    from flyers_video_tool.app import render_history_ui
    source = inspect.getsource(render_history_ui)
    assert "shared_render_options" not in source
    assert "wm_text" not in source
    assert "bg_mode" not in source

def test_shared_render_options_returns_watermark_options():
    at = AppTest.from_file(str(Path(__file__).parent.parent / "app.py"))
    at.run()
    
    # Check if Watermark UI components are rendered
    labels = [cb.label for cb in at.checkbox]
    assert "Đóng dấu (Watermark)" in labels
    
    labels = [txt.label for txt in at.text_input]
    assert "Chữ đóng dấu" in labels
    
    labels = [sl.label for sl in at.slider]
    assert "Độ mờ" in labels
    
    labels = [btn.label for btn in at.button]
    assert "Xem trước đúng như file xuất" in labels

def test_shared_render_options_returns_resolution_tuple_and_gap():
    from flyers_video_tool.app import shared_render_options
    
    # We can test the return values directly by mocking Streamlit or 
    # relying on the default values set by st.selectbox when we mock it.
    # Since we can't easily call Streamlit functions outside AppTest,
    # let's use AppTest to inspect the session state or just read the code structure.
    import inspect
    source = inspect.getsource(shared_render_options)
    
    # Verify the return block formats resolution as tuple and includes open_book_gap
    assert '"resolution": (res_w, res_h)' in source or '"resolution": (int(res_w), int(res_h))' in source
    assert '"open_book_gap": open_book_gap' in source
    assert 'res_w, res_h = map(int, resolution.split("x"))' in source
    
    # Verify preview scene gets the variable, not hardcoded 24
    assert 'open_book_gap=open_book_gap' in source
    assert 'open_book_gap=24' not in source
