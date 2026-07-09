import pytest
from flyers_video_tool.flyers_video_tool import _watermark_position

def test_watermark_position_3x3():
    canvas = (1920, 1080)
    mark = (100, 50)
    margin = 32
    
    assert _watermark_position(canvas, mark, "top-left", margin) == (32, 32)
    assert _watermark_position(canvas, mark, "bottom-right", margin) == (1920 - 100 - 32, 1080 - 50 - 32)
    assert _watermark_position(canvas, mark, "top-center", margin) == ((1920 - 100) // 2, 32)
    assert _watermark_position(canvas, mark, "center", margin) == ((1920 - 100) // 2, (1080 - 50) // 2)
    assert _watermark_position(canvas, mark, "center-left", margin) == (32, (1080 - 50) // 2)
