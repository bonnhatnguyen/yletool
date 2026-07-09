import pytest
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock, call

from flyers_video_tool.flyers_video_tool import _get_available_h264_encoders, create_video

def test_get_available_h264_encoders_all():
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = "h264_nvenc h264_qsv h264_amf"
        mock_run.return_value = mock_result
        
        encoders = _get_available_h264_encoders()
        assert len(encoders) == 4
        assert encoders[0][0] == "h264_nvenc"
        assert encoders[0][1]["preset"] == "fast"
        assert encoders[1][0] == "h264_qsv"
        assert encoders[1][1]["preset"] == "veryfast"
        assert encoders[2][0] == "h264_amf"
        assert encoders[2][1]["quality"] == "speed"
        assert encoders[3][0] == "libx264"
        assert encoders[3][1]["preset"] == "ultrafast"

def test_get_available_h264_encoders_fallback_only():
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = Exception("ffmpeg not found")
        
        encoders = _get_available_h264_encoders()
        assert len(encoders) == 1
        assert encoders[0][0] == "libx264"
        assert encoders[0][1]["preset"] == "ultrafast"

@patch("flyers_video_tool.flyers_video_tool.tempfile.TemporaryDirectory")
@patch("flyers_video_tool.flyers_video_tool._check_ffmpeg_available")
@patch("flyers_video_tool.flyers_video_tool.render_pdf_page")
@patch("flyers_video_tool.flyers_video_tool.make_pages_scene")
@patch("flyers_video_tool.flyers_video_tool.apply_watermark_to_scene")
@patch("flyers_video_tool.flyers_video_tool.get_audio_duration")
@patch("flyers_video_tool.flyers_video_tool._get_available_h264_encoders")
@patch("subprocess.run")
@patch("shutil.move")
def test_fast_static_creates_concat_file_and_fallbacks(
    mock_move, mock_run, mock_get_encoders, mock_get_audio_duration, mock_watermark, mock_make_scene, mock_render_pdf, mock_check_ffmpeg, mock_tempdir, tmp_path
):
    mock_get_audio_duration.return_value = 10.0
    mock_render_pdf.return_value = tmp_path / "page_1.jpg"
    
    # Return 3 encoders, first two will fail, last one succeeds
    mock_get_encoders.return_value = [
        ("h264_nvenc", {"preset": "fast"}),
        ("h264_qsv", {"preset": "veryfast"}),
        ("libx264", {"preset": "ultrafast"})
    ]
    
    # Subprocess will raise CalledProcessError twice, then return success
    def side_effect(*args, **kwargs):
        if "h264_nvenc" in args[0] or "h264_qsv" in args[0]:
            raise subprocess.CalledProcessError(1, args[0], stderr="Error")
        return MagicMock()
        
    mock_run.side_effect = side_effect
    
    mock_temp_obj = MagicMock()
    mock_temp_obj.name = str(tmp_path)
    mock_tempdir.return_value = mock_temp_obj
    
    pdf_path = tmp_path / "test.pdf"
    pdf_path.touch()
    audio_path = tmp_path / "test.mp3"
    audio_path.touch()
    output_path = tmp_path / "out.mp4"
    
    timestamp_rows = [
        {"start_seconds": 0.0, "end_seconds": 5.0, "pdf_pages": [1]},
        {"start_seconds": 5.0, "end_seconds": 10.0, "pdf_pages": [2]}
    ]
    
    create_video(
        pdf_path=pdf_path,
        audio_path=audio_path,
        output_path=output_path,
        timestamp_rows=timestamp_rows,
        export_mode="fast_static",
        fps=1,
        transition_effect="crossfade" # should be forced to none
    )
    
    # Check that subprocess.run was called 3 times
    assert mock_run.call_count == 3
    
    # First call was nvenc, no -tune stillimage
    assert "h264_nvenc" in mock_run.call_args_list[0][0][0]
    assert "-tune" not in mock_run.call_args_list[0][0][0]
    
    # Second call was qsv, no -tune stillimage
    assert "h264_qsv" in mock_run.call_args_list[1][0][0]
    assert "-tune" not in mock_run.call_args_list[1][0][0]
    
    # Third call was libx264, has -tune stillimage
    assert "libx264" in mock_run.call_args_list[2][0][0]
    assert "-tune" in mock_run.call_args_list[2][0][0]
    assert "stillimage" in mock_run.call_args_list[2][0][0]
    
    # Check shutil.move was called once
    mock_move.assert_called_once()
    
    # Check that concat files are correct
    concat_files = list(tmp_path.glob("concat.txt"))
    assert len(concat_files) == 1
    
    concat_content = concat_files[0].read_text(encoding="utf-8")
    assert "file '" in concat_content
    assert "duration 5.000" in concat_content
    assert concat_content.count("file '") == 3
    assert concat_content.count("duration ") == 2

@patch("flyers_video_tool.flyers_video_tool.tempfile.TemporaryDirectory")
@patch("flyers_video_tool.flyers_video_tool._check_ffmpeg_available")
@patch("flyers_video_tool.flyers_video_tool.render_pdf_page")
@patch("flyers_video_tool.flyers_video_tool.make_pages_scene")
@patch("flyers_video_tool.flyers_video_tool.apply_watermark_to_scene")
@patch("flyers_video_tool.flyers_video_tool.get_audio_duration")
@patch("flyers_video_tool.flyers_video_tool._get_available_h264_encoders")
@patch("subprocess.run")
def test_fast_static_fails_completely(
    mock_run, mock_get_encoders, mock_get_audio_duration, mock_watermark, mock_make_scene, mock_render_pdf, mock_check_ffmpeg, mock_tempdir, tmp_path
):
    mock_get_audio_duration.return_value = 10.0
    mock_render_pdf.return_value = tmp_path / "page_1.jpg"
    mock_get_encoders.return_value = [("libx264", {"preset": "ultrafast"})]
    mock_run.side_effect = subprocess.CalledProcessError(1, "ffmpeg", stderr="Fatal error")
    
    mock_temp_obj = MagicMock()
    mock_temp_obj.name = str(tmp_path)
    mock_tempdir.return_value = mock_temp_obj
    
    pdf_path = tmp_path / "test.pdf"
    pdf_path.touch()
    audio_path = tmp_path / "test.mp3"
    audio_path.touch()
    output_path = tmp_path / "out.mp4"
    
    timestamp_rows = [
        {"start_seconds": 0.0, "end_seconds": 10.0, "pdf_pages": [1]}
    ]
    
    with pytest.raises(RuntimeError, match="Tất cả các bộ mã hóa đều thất bại"):
        create_video(
            pdf_path=pdf_path,
            audio_path=audio_path,
            output_path=output_path,
            timestamp_rows=timestamp_rows,
            export_mode="fast_static"
        )
