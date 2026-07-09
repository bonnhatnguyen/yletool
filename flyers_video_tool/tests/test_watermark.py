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

import pytest
from pathlib import Path
from PIL import Image
from flyers_video_tool.flyers_video_tool import apply_watermark_to_scene

def test_invalid_watermark_image_raises_friendly_error(tmp_path):
    invalid_img = tmp_path / "invalid.jpg"
    invalid_img.write_text("placeholder")
    
    scene_img = tmp_path / "scene.jpg"
    Image.new('RGB', (100, 100)).save(scene_img)
    
    options = {
        "enabled": True,
        "image": str(invalid_img),
        "position": "center",
        "opacity": 0.5,
        "size": 50,
        "margin": 10
    }
    
    with pytest.raises(RuntimeError, match="File watermark không phải ảnh hợp lệ"):
        apply_watermark_to_scene(scene_img, tmp_path / "out.jpg", options)

def test_valid_watermark_image_applies_correctly(tmp_path):
    valid_img = tmp_path / "valid.png"
    Image.new('RGBA', (50, 50)).save(valid_img)
    
    scene_img = tmp_path / "scene.jpg"
    Image.new('RGB', (100, 100)).save(scene_img)
    out_img = tmp_path / "out.jpg"
    
    options = {
        "enabled": True,
        "image": str(valid_img),
        "position": "center",
        "opacity": 0.5,
        "size": 50,
        "margin": 10
    }
    
    apply_watermark_to_scene(scene_img, out_img, options)
    assert out_img.exists()
