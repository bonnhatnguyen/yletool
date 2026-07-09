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
