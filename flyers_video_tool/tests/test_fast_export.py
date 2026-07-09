import pytest
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

from flyers_video_tool.flyers_video_tool import _get_best_h264_encoder, create_video

def test_get_best_h264_encoder_nvidia():
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = "V....D h264_nvenc NVIDIA NVENC H.264 encoder"
        mock_run.return_value = mock_result
        
        encoder, opts = _get_best_h264_encoder()
        assert encoder == "h264_nvenc"
        assert opts["preset"] == "fast"

def test_get_best_h264_encoder_fallback():
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = Exception("ffmpeg not found")
        
        encoder, opts = _get_best_h264_encoder()
        assert encoder == "libx264"
        assert opts["preset"] == "ultrafast"

@patch("flyers_video_tool.flyers_video_tool.tempfile.TemporaryDirectory")
@patch("flyers_video_tool.flyers_video_tool._check_ffmpeg_available")
@patch("flyers_video_tool.flyers_video_tool.render_pdf_page")
@patch("flyers_video_tool.flyers_video_tool.make_pages_scene")
@patch("flyers_video_tool.flyers_video_tool.apply_watermark_to_scene")
@patch("flyers_video_tool.flyers_video_tool.get_audio_duration")
@patch("flyers_video_tool.flyers_video_tool._get_best_h264_encoder")
@patch("subprocess.run")
def test_fast_static_creates_concat_file(
    mock_run, mock_get_encoder, mock_get_audio_duration, mock_watermark, mock_make_scene, mock_render_pdf, mock_check_ffmpeg, mock_tempdir, tmp_path
):
    # Setup mocks
    mock_get_audio_duration.return_value = 10.0
    mock_render_pdf.return_value = tmp_path / "page_1.jpg"
    mock_get_encoder.return_value = ("libx264", {"preset": "ultrafast"})
    
    # Mock tempdir to return our tmp_path
    mock_temp_obj = MagicMock()
    mock_temp_obj.name = str(tmp_path)
    mock_tempdir.return_value = mock_temp_obj
    
    # Setup inputs
    pdf_path = tmp_path / "test.pdf"
    pdf_path.touch()
    audio_path = tmp_path / "test.mp3"
    audio_path.touch()
    output_path = tmp_path / "out.mp4"
    
    timestamp_rows = [
        {"start_seconds": 0.0, "end_seconds": 5.0, "pdf_pages": [1]},
        {"start_seconds": 5.0, "end_seconds": 10.0, "pdf_pages": [2]}
    ]
    
    # Call create_video
    create_video(
        pdf_path=pdf_path,
        audio_path=audio_path,
        output_path=output_path,
        timestamp_rows=timestamp_rows,
        export_mode="fast_static",
        fps=2
    )
    
    # Verify concat.txt was created properly
    concat_files = list(tmp_path.glob("concat.txt"))
    assert len(concat_files) == 1
    
    concat_content = concat_files[0].read_text(encoding="utf-8")
    assert "file '" in concat_content
    assert "duration 5.000" in concat_content
    
    # Count how many times 'file' appears. Should be 3 times (2 for the scenes, 1 repeat at the end)
    assert concat_content.count("file '") == 3
    assert concat_content.count("duration ") == 2
    
    # Verify subprocess.run was called with ffmpeg
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "ffmpeg"
    assert "-f" in cmd
    assert "concat" in cmd
    assert "-r" in cmd
    assert "2" in cmd
