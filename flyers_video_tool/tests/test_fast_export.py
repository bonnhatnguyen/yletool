import pytest
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock, call

from flyers_video_tool.flyers_video_tool import _get_available_h264_encoders, create_video
import os

def test_get_available_h264_encoders_all():
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = "h264_nvenc h264_qsv h264_amf"
        mock_run.return_value = mock_result
        
        encoders = _get_available_h264_encoders(use_gpu=True)
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
        
        encoders = _get_available_h264_encoders(use_gpu=True)
        assert len(encoders) == 1
        assert encoders[0][0] == "libx264"
        assert encoders[0][1]["preset"] == "ultrafast"

def test_get_available_h264_encoders_no_gpu():
    with patch("subprocess.run") as mock_run:
        encoders = _get_available_h264_encoders(use_gpu=False)
        assert len(encoders) == 1
        assert encoders[0][0] == "libx264"
        mock_run.assert_not_called()

@patch("flyers_video_tool.flyers_video_tool.tempfile.TemporaryDirectory")
@patch("flyers_video_tool.flyers_video_tool._check_ffmpeg_available")
@patch("flyers_video_tool.flyers_video_tool.render_pdf_page")
@patch("flyers_video_tool.flyers_video_tool.make_pages_scene")
@patch("flyers_video_tool.flyers_video_tool.apply_watermark_to_scene")
@patch("flyers_video_tool.flyers_video_tool.get_audio_duration")
@patch("flyers_video_tool.flyers_video_tool._get_available_h264_encoders")
@patch("subprocess.run")
@patch("os.replace")
@patch("flyers_video_tool.flyers_video_tool.get_format_duration")
@patch("flyers_video_tool.flyers_video_tool.get_stream_durations")
def test_fast_static_creates_concat_file_and_fallbacks(
    mock_get_stream, mock_get_format, mock_replace, mock_run, mock_get_encoders, mock_get_audio_duration, mock_watermark, mock_make_scene, mock_render_pdf, mock_check_ffmpeg, mock_tempdir, tmp_path
):
    mock_get_audio_duration.return_value = 10.0
    mock_get_format.return_value = 10.0
    mock_get_stream.return_value = (10.0, 10.0)
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
    
    # Verify command line arguments
    libx264_cmd = mock_run.call_args_list[2][0][0]
    assert "-shortest" not in libx264_cmd
    assert "-t" in libx264_cmd
    assert "10.000" in libx264_cmd
    
    # Check for tpad filter
    vf_idx = libx264_cmd.index("-vf")
    assert "tpad=stop_mode=clone" in libx264_cmd[vf_idx + 1]

    # Check shutil.move was called once
    mock_replace.assert_called_once()
    
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
            
        )

def test_fast_static_duration_guard(tmp_path):
    pdf_path = tmp_path / "test.pdf"
    pdf_path.touch()
    audio_path = tmp_path / "test.mp3"
    audio_path.touch()
    output_path = tmp_path / "out.mp4"
    
    # Delta > 5.0 (20.0 - 10.0 = 10.0) -> blocks
    timestamp_rows = [
        {"start_seconds": 0.0, "end_seconds": 10.0, "pdf_pages": [1]}
    ]
    
    with patch("flyers_video_tool.flyers_video_tool.get_audio_duration", return_value=20.0):
        with patch("flyers_video_tool.flyers_video_tool._check_ffmpeg_available"):
            with patch("flyers_video_tool.flyers_video_tool.render_pdf_page"):
                with patch("flyers_video_tool.flyers_video_tool.make_pages_scene"):
                    with patch("flyers_video_tool.flyers_video_tool.apply_watermark_to_scene"):
                        with pytest.raises(RuntimeError, match="Tổng thời gian các Part không khớp audio"):
                            create_video(pdf_path, audio_path, timestamp_rows, output_path, )
                
    # Delta <= 5.0 (12.0 - 10.0 = 2.0) -> adjusts
    with patch("flyers_video_tool.flyers_video_tool.get_audio_duration", return_value=12.0):
        with patch("flyers_video_tool.flyers_video_tool._check_ffmpeg_available"):
            with patch("flyers_video_tool.flyers_video_tool.render_pdf_page", return_value=tmp_path / "page.jpg"):
                with patch("flyers_video_tool.flyers_video_tool.make_pages_scene"):
                    with patch("flyers_video_tool.flyers_video_tool.apply_watermark_to_scene"):
                        with patch("flyers_video_tool.flyers_video_tool._get_available_h264_encoders", return_value=[("libx264", {})]):
                            with patch("subprocess.run"):
                                with patch("os.replace"):
                                        with patch("flyers_video_tool.flyers_video_tool.get_format_duration", return_value=12.0):
                                            with patch("flyers_video_tool.flyers_video_tool.get_stream_durations", return_value=(12.0, 12.0)):
                                                # Should not raise exception
                                                create_video(pdf_path, audio_path, timestamp_rows, output_path, )

def test_part1_cover_and_absolute_timeline(tmp_path):
    pdf_path = tmp_path / "test.pdf"
    pdf_path.touch()
    audio_path = tmp_path / "test.mp3"
    audio_path.touch()
    output_path = tmp_path / "out.mp4"
    
    timestamp_rows = [
        {"title": "Part 1", "start_seconds": 26.0, "end_seconds": 354.0, "pdf_pages": [2]},
        {"title": "Part 2", "start_seconds": 354.0, "end_seconds": 560.0, "pdf_pages": [3]}
    ]
    
    with patch("flyers_video_tool.flyers_video_tool.get_audio_duration", return_value=560.0):
        with patch("flyers_video_tool.flyers_video_tool._check_ffmpeg_available"):
            with patch("flyers_video_tool.flyers_video_tool.render_pdf_page", return_value=tmp_path / "page.jpg"):
                with patch("flyers_video_tool.flyers_video_tool.make_pages_scene") as mock_make:
                    with patch("flyers_video_tool.flyers_video_tool.apply_watermark_to_scene"):
                        with patch("flyers_video_tool.flyers_video_tool._get_available_h264_encoders", return_value=[("libx264", {})]):
                            with patch("subprocess.run"):
                                with patch("os.replace"):
                                    with patch("flyers_video_tool.flyers_video_tool.get_format_duration", return_value=560.0):
                                        with patch("flyers_video_tool.flyers_video_tool.get_stream_durations", return_value=(560.0, 560.0)):
                                            # Call create_video
                                            create_video(pdf_path, audio_path, timestamp_rows, output_path, include_cover_with_part1=True, cover_page=1)
                                            
                                            # First call to make_pages_scene should have 2 pages (cover + part1)
                                            assert len(mock_make.call_args_list[0][0][0]) == 2
                                            assert mock_make.call_args_list[0][0][2] == "auto" # Layout forced to auto
                                            
                                            # Second call should have 1 page (part2)
                                            assert len(mock_make.call_args_list[1][0][0]) == 1
                                            
                                            # Now check concat.txt
                                            concat_files = list(tmp_path.glob("**/concat.txt"))
                                            if concat_files:
                                                content = concat_files[0].read_text(encoding="utf-8")
                                                # Duration of first scene should be 354 (absolute)
                                                assert "duration 354.000" in content
                                                # Duration of second scene should be 560 - 354 = 206
                                                assert "duration 206.000" in content

@patch("flyers_video_tool.flyers_video_tool.tempfile.TemporaryDirectory")
@patch("flyers_video_tool.flyers_video_tool._check_ffmpeg_available")
@patch("flyers_video_tool.flyers_video_tool.render_pdf_page")
@patch("flyers_video_tool.flyers_video_tool.make_pages_scene")
@patch("flyers_video_tool.flyers_video_tool.apply_watermark_to_scene")
@patch("flyers_video_tool.flyers_video_tool.get_audio_duration")
@patch("flyers_video_tool.flyers_video_tool._get_available_h264_encoders")
@patch("subprocess.run")
@patch("flyers_video_tool.flyers_video_tool.get_format_duration")
@patch("flyers_video_tool.flyers_video_tool.get_stream_durations")
@patch("os.replace")
def test_fast_static_ffprobe_rejects_long_video(
    mock_replace, mock_get_stream, mock_get_format, mock_run, mock_get_encoders, mock_get_audio_duration, mock_watermark, mock_make_scene, mock_render_pdf, mock_check_ffmpeg, mock_tempdir, tmp_path
):
    mock_get_audio_duration.return_value = 1763.11
    mock_get_format.return_value = 2100.00
    mock_get_stream.return_value = (2100.00, 1763.11)
    mock_render_pdf.return_value = tmp_path / "page_1.jpg"
    mock_get_encoders.return_value = [("libx264", {})]
    mock_run.return_value = MagicMock()
    
    mock_temp_obj = MagicMock()
    mock_temp_obj.name = str(tmp_path)
    mock_tempdir.return_value = mock_temp_obj
    
    pdf_path = tmp_path / "test.pdf"
    pdf_path.touch()
    audio_path = tmp_path / "test.mp3"
    audio_path.touch()
    output_path = tmp_path / "out.mp4"
    
    timestamp_rows = [
        {"start_seconds": 0.0, "end_seconds": 1763.11, "pdf_pages": [1]}
    ]
    
    with pytest.raises(RuntimeError, match="Tất cả các bộ mã hóa đều thất bại"):
        create_video(pdf_path, audio_path, timestamp_rows, output_path, )
        
    mock_replace.assert_not_called()
    assert "-t" in mock_run.call_args_list[0][0][0]
    assert "1763.110" in mock_run.call_args_list[0][0][0]

def test_validate_or_repair_output_duration_audio_missing_format_ok():
    from flyers_video_tool.flyers_video_tool import validate_or_repair_output_duration
    with patch('flyers_video_tool.flyers_video_tool.get_format_duration') as mock_fmt, \
         patch('flyers_video_tool.flyers_video_tool.get_stream_durations') as mock_stream:
        mock_fmt.return_value = 10.5
        mock_stream.return_value = (None, None)
        valid, msg = validate_or_repair_output_duration(Path('dummy.mp4'), 10.0, 1, 'libx264')
        assert valid
        assert 'attempted repair: no' in msg

def test_validate_or_repair_output_duration_audio_ok_format_long():
    from flyers_video_tool.flyers_video_tool import validate_or_repair_output_duration
    with patch('flyers_video_tool.flyers_video_tool.get_format_duration') as mock_fmt, \
         patch('flyers_video_tool.flyers_video_tool.get_stream_durations') as mock_stream, \
         patch('subprocess.run') as mock_run, \
         patch('os.replace'):
        mock_fmt.side_effect = [14.0, 10.0]
        mock_stream.side_effect = [(None, 10.0), (None, 10.0)]
        
        valid, msg = validate_or_repair_output_duration(Path('dummy.mp4'), 10.0, 1, 'libx264')
        
        assert valid
        assert 'attempted repair: yes (copy)' in msg
        mock_run.assert_called()

def test_validate_or_repair_output_duration_audio_wrong():
    from flyers_video_tool.flyers_video_tool import validate_or_repair_output_duration
    with patch('flyers_video_tool.flyers_video_tool.get_format_duration') as mock_fmt, \
         patch('flyers_video_tool.flyers_video_tool.get_stream_durations') as mock_stream:
        mock_fmt.return_value = 15.0
        mock_stream.return_value = (None, 15.0)
        
        valid, msg = validate_or_repair_output_duration(Path('dummy.mp4'), 10.0, 1, 'libx264')
        assert not valid
        assert 'Validation failed: Audio stream length mismatch' in msg

def test_validate_or_repair_output_duration_audio_truncated():
    from flyers_video_tool.flyers_video_tool import validate_or_repair_output_duration
    with patch('flyers_video_tool.flyers_video_tool.get_format_duration') as mock_fmt, \
         patch('flyers_video_tool.flyers_video_tool.get_stream_durations') as mock_stream:
        mock_fmt.return_value = 5.0
        mock_stream.return_value = (None, 5.0)
        
        valid, msg = validate_or_repair_output_duration(Path('dummy.mp4'), 100.0, 1, 'libx264')
        assert not valid
        assert 'Validation failed: Output was truncated' in msg
