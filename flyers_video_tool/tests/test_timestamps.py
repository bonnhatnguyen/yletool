import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from flyers_video_tool.flyers_video_tool import (
    detect_part_timestamps,
    detect_timestamps_with_gemini_fallback,
    normalize_page_map_config,
    normalize_watermark_options
)

# Test A: Whisper/local segment detection test
def test_whisper_normal_detection():
    fake_segments = [
        {"start": 0.0, "end": 4.0, "text": "Cambridge Flyers Listening Test 1"},
        {"start": 5.0, "end": 8.0, "text": "Part One. Listen and look."},
        {"start": 120.0, "end": 124.0, "text": "Part Two. Listen and write."},
        {"start": 240.0, "end": 244.0, "text": "Part Three. Listen and draw lines."},
        {"start": 360.0, "end": 364.0, "text": "Part Four. Listen and tick."},
        {"start": 480.0, "end": 484.0, "text": "Part Five. Listen and colour."}
    ]
    
    config = {
        "parts": [
            {"part": 1, "title": "Part 1", "pages": [5]},
            {"part": 2, "title": "Part 2", "pages": [6]},
            {"part": 3, "title": "Part 3", "pages": [7]},
            {"part": 4, "title": "Part 4", "pages": [8]},
            {"part": 5, "title": "Part 5", "pages": [9]},
        ]
    }
    
    rows, warnings = detect_part_timestamps(fake_segments, 600.0, page_map_config=config)
    assert not warnings
    assert len(rows) == 5
    assert rows[0]["start_seconds"] == 5.0
    assert rows[1]["start_seconds"] == 120.0
    assert rows[2]["start_seconds"] == 240.0
    assert rows[3]["start_seconds"] == 360.0
    assert rows[4]["start_seconds"] == 480.0
    assert rows[4]["end_seconds"] == 600.0


# Test B: Missing part fallback test
def test_missing_part_fallback():
    fake_segments = [
        {"start": 5.0, "end": 8.0, "text": "Part One."},
        {"start": 120.0, "end": 124.0, "text": "Part Two."},
        # Part 3 missing
        {"start": 360.0, "end": 364.0, "text": "Part Four."},
        {"start": 480.0, "end": 484.0, "text": "Part Five."}
    ]
    
    config = {
        "parts": [
            {"part": 1, "title": "Part 1", "pages": [5]},
            {"part": 2, "title": "Part 2", "pages": [6]},
            {"part": 3, "title": "Part 3", "pages": [7]},
            {"part": 4, "title": "Part 4", "pages": [8]},
            {"part": 5, "title": "Part 5", "pages": [9]},
        ]
    }
    
    rows, warnings = detect_part_timestamps(fake_segments, 600.0, page_map_config=config)
    assert len(warnings) > 0
    assert any("not detected" in w and "Part 3" in w for w in warnings)
    assert len(rows) == 5
    assert rows[2]["start_seconds"] == 120.0  # Fallbacks to Part 2's start
    assert rows[3]["start_seconds"] == 360.0


# Test C: Dynamic part count test (e.g. Starters has 4 parts)
def test_dynamic_part_count():
    fake_segments = [
        {"start": 5.0, "end": 8.0, "text": "Part One."},
        {"start": 120.0, "end": 124.0, "text": "Part Two."},
        {"start": 240.0, "end": 244.0, "text": "Part Three."},
        {"start": 360.0, "end": 364.0, "text": "Part Four."},
        {"start": 480.0, "end": 484.0, "text": "Part Five."} # Extra part should be ignored
    ]
    
    config = {
        "parts": [
            {"part": 1, "title": "Part 1", "pages": [5]},
            {"part": 2, "title": "Part 2", "pages": [6]},
            {"part": 3, "title": "Part 3", "pages": [7]},
            {"part": 4, "title": "Part 4", "pages": [8]},
        ]
    }
    
    rows, warnings = detect_part_timestamps(fake_segments, 400.0, page_map_config=config)
    assert len(rows) == 4
    assert rows[-1]["end_seconds"] == 400.0



from flyers_video_tool.flyers_video_tool import detect_timestamps_with_gemini_fallback, get_gemini_api_keys

@patch('google.genai.Client')
@patch('flyers_video_tool.flyers_video_tool.get_gemini_api_keys')
def test_gemini_json_to_timestamps(mock_get_keys, mock_client_class):
    mock_get_keys.return_value = ["fake_key"]
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    
    mock_file = MagicMock()
    mock_file.name = "fake_file"
    mock_client.files.upload.return_value = mock_file
    
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "parts": [
            {"part": 1, "start": "00:05", "confidence": 0.95},
            {"part": 2, "start": "02:00", "confidence": 0.9},
            {"part": 3, "start": "04:00", "confidence": 0.9},
            {"part": 4, "start": "06:00", "confidence": 0.9},
            {"part": 5, "start": "08:00", "confidence": 0.9}
        ],
        "warnings": []
    })
    mock_client.models.generate_content.return_value = mock_response
    
    config = {
        "parts": [
            {"part": 1, "title": "Part 1", "pages": [5], "layout": "auto"},
            {"part": 2, "title": "Part 2", "pages": [6], "layout": "auto"},
            {"part": 3, "title": "Part 3", "pages": [7], "layout": "auto"},
            {"part": 4, "title": "Part 4", "pages": [8], "layout": "auto"},
            {"part": 5, "title": "Part 5", "pages": [9], "layout": "auto"},
        ]
    }
    
    segments = detect_timestamps_with_gemini_fallback(Path("fake.mp3"), config)
    assert len(segments) == 5
    assert segments[0]["start"] == 5.0
    assert segments[1]["start"] == 120.0
    assert segments[4]["start"] == 480.0
    
    rows, warnings = detect_part_timestamps(segments, 600.0, page_map_config=config)
    assert len(rows) == 5
    assert rows[0]["start_seconds"] == 5.0
    assert rows[1]["start_seconds"] == 120.0
    assert rows[4]["start_seconds"] == 480.0
    assert rows[4]["end_seconds"] == 600.0


@patch('google.genai.Client')
@patch('flyers_video_tool.flyers_video_tool.get_gemini_api_keys')
def test_gemini_bad_json(mock_get_keys, mock_client_class):
    mock_get_keys.return_value = ["fake_key"]
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    
    mock_file = MagicMock()
    mock_file.name = "fake_file"
    mock_client.files.upload.return_value = mock_file
    
    mock_response = MagicMock()
    mock_response.text = "this is not json"
    mock_client.models.generate_content.return_value = mock_response
    
    config = {"parts": [{"part": 1, "title": "Part 1", "pages": [5]}]}
    
    try:
        segments = detect_timestamps_with_gemini_fallback(Path("fake.mp3"), config)
        pytest.fail("Should have raised exception on bad JSON")
    except RuntimeError as e:
        assert "Gemini không khả dụng" in str(e)



# Test: Watermark UI mapping test
def test_watermark_position_mapping():
    watermark_position_map = {
        "dưới-phải": "bottom-right",
        "dưới-trái": "bottom-left",
        "trên-phải": "top-right",
        "trên-trái": "top-left",
        "giữa": "center",
    }
    assert watermark_position_map["dưới-phải"] == "bottom-right"
    assert watermark_position_map["dưới-trái"] == "bottom-left"
    assert watermark_position_map["trên-phải"] == "top-right"
    assert watermark_position_map["trên-trái"] == "top-left"
    assert watermark_position_map["giữa"] == "center"

    opts = normalize_watermark_options(
        enabled=True,
        text="test",
        position=watermark_position_map["dưới-phải"]
    )
    assert opts["position"] == "bottom-right"
