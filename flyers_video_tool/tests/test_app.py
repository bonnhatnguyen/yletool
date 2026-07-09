import pytest
import pandas as pd
from pathlib import Path
from unittest.mock import patch

from flyers_video_tool.app import clean_timestamp_dataframe, dataframe_to_rows

def test_clean_timestamp_dataframe_ignores_fully_blank_row():
    df = pd.DataFrame([
        {"title": "Part 1", "start": "0", "end": "60", "pdf_pages": "1,2", "layout": "side_by_side"},
        {"title": None, "start": None, "end": None, "pdf_pages": None, "layout": None},
        {"title": "", "start": "", "end": "", "pdf_pages": "", "layout": ""}
    ])
    cleaned = clean_timestamp_dataframe(df)
    assert len(cleaned) == 1
    assert cleaned.iloc[0]["title"] == "Part 1"

def test_clean_timestamp_dataframe_raises_friendly_error_missing_start():
    df = pd.DataFrame([
        {"title": "Part 1", "start": None, "end": "60", "pdf_pages": "1,2", "layout": "side_by_side"}
    ])
    with pytest.raises(ValueError, match="Dòng Part 1 thiếu start."):
        clean_timestamp_dataframe(df)

def test_clean_timestamp_dataframe_raises_friendly_error_missing_end():
    df = pd.DataFrame([
        {"title": "Part 2", "start": "60", "end": None, "pdf_pages": "3,4", "layout": "side_by_side"}
    ])
    with pytest.raises(ValueError, match="Dòng Part 2 thiếu end."):
        clean_timestamp_dataframe(df)

def test_clean_timestamp_dataframe_raises_friendly_error_missing_pdf_pages():
    df = pd.DataFrame([
        {"title": "Part 3", "start": "120", "end": "180", "pdf_pages": None, "layout": "side_by_side"}
    ])
    with pytest.raises(ValueError, match="Dòng Part 3 thiếu pdf_pages."):
        clean_timestamp_dataframe(df)

def test_clean_timestamp_dataframe_raises_friendly_error_multiple_missing():
    df = pd.DataFrame([
        {"title": "Part 4", "start": None, "end": None, "pdf_pages": None, "layout": "side_by_side"}
    ])
    with pytest.raises(ValueError, match="Dòng Part 4 thiếu start/end/pdf_pages."):
        clean_timestamp_dataframe(df)

def test_dataframe_to_rows_empty_raises_friendly_error():
    df = pd.DataFrame(columns=["title", "start", "end", "pdf_pages", "layout"])
    with pytest.raises(ValueError, match="Bảng thời gian đang trống"):
        dataframe_to_rows(df)

def test_dataframe_to_rows_ignores_blank_row(tmp_path):
    df = pd.DataFrame([
        {"title": "Part 1", "start": "0", "end": "60", "pdf_pages": "1,2", "layout": "side_by_side"},
        {"title": None, "start": None, "end": None, "pdf_pages": None, "layout": None}
    ])
    with patch('flyers_video_tool.app.session_dir', return_value=tmp_path):
        with patch('flyers_video_tool.app.parse_timestamps_csv', return_value=[{}]) as mock_parse:
            dataframe_to_rows(df)
            mock_parse.assert_called_once()
