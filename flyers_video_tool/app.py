import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st
from typing import Optional

from flyers_video_tool import (
    auto_detect_page_map_from_pdf,
    create_video,
    detect_part_timestamps,
    discover_batch_pairs,
    export_page_map_config,
    export_detected_timestamps,
    get_preset_page_map,
    get_audio_duration,
    infer_test_number_from_name,
    load_page_map_config,
    normalize_watermark_options,
    parse_timestamps_csv,
    process_batch,
    read_pairing_csv,
    transcribe_audio,
)


st.set_page_config(page_title="Flyers Video Tool", layout="wide")


def session_dir() -> Path:
    if "work_dir" not in st.session_state:
        st.session_state.work_dir = tempfile.mkdtemp(prefix="flyers_streamlit_")
    return Path(st.session_state.work_dir)


def save_upload(uploaded_file, subdir: str = "uploads") -> Path:
    path = session_dir() / subdir / uploaded_file.name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(uploaded_file.getbuffer())
    return path


def seconds_to_text(seconds: float) -> str:
    total = max(0, int(round(float(seconds))))
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def rows_to_dataframe(rows):
    return pd.DataFrame(
        [
            {
                "title": row["title"],
                "start": row.get("start") or seconds_to_text(row["start_seconds"]),
                "end": row.get("end") or seconds_to_text(row["end_seconds"]),
                "pdf_pages": ",".join(str(page) for page in row["pdf_pages"]),
                "layout": row.get("layout", "auto"),
            }
            for row in rows
        ]
    )


def dataframe_to_rows(dataframe: pd.DataFrame):
    csv_path = session_dir() / "edited_timestamps.csv"
    dataframe[["title", "start", "end", "pdf_pages", "layout"]].to_csv(csv_path, index=False)
    return parse_timestamps_csv(csv_path)


def page_map_to_dataframe(config: dict):
    return pd.DataFrame(
        [
            {
                "Part": part["part"],
                "Tiêu đề": part["title"],
                "Số trang sách (in)": ",".join(str(page) for page in part.get("printed_pages", [])),
                "Số trang PDF thực tế": ",".join(str(page) for page in part["pages"]),
                "Bố cục": part["layout"],
                "Khóa trang PDF này": False,
            }
            for part in config["parts"]
        ]
    )


def page_map_dataframe_to_config(dataframe: pd.DataFrame, level: str, test_number: int, pdf_offset: Optional[int] = None):
    parts = []
    for _, row in dataframe.iterrows():
        pages = [int(value.strip()) for value in str(row["Số trang PDF thực tế"]).replace(";", ",").split(",") if value.strip() and value.strip() != "nan"]
        printed_pages_str = str(row.get("Số trang sách (in)", ""))
        printed_pages = [int(value.strip()) for value in printed_pages_str.replace(";", ",").split(",") if value.strip() and value.strip() != "nan"]
        part_dict = {
            "part": int(row["Part"]),
            "title": str(row.get("Tiêu đề") or f"Part {int(row['Part'])}"),
            "pages": pages,
            "layout": str(row.get("Bố cục") or "auto"),
        }
        if printed_pages:
            part_dict["printed_pages"] = printed_pages
        parts.append(part_dict)
    
    config = {"level": level.lower(), "test": int(test_number), "parts": parts}
    if pdf_offset is not None:
        config["pdf_offset"] = pdf_offset
    return config


def default_rows_for_page_map(config: dict):
    rows = []
    start = 0
    for part in config["parts"]:
        rows.append(
            {
                "title": part["title"],
                "start_seconds": start,
                "end_seconds": start + 60,
                "pdf_pages": part["pages"],
                "layout": part["layout"],
            }
        )
        start += 60
    return rows


def shared_render_options(prefix: str):
    cols = st.columns(5)
    with cols[0]:
        resolution = st.selectbox("Độ phân giải", ["1920x1080", "3840x2160"], key=f"{prefix}_resolution")
    with cols[1]:
        background = st.selectbox("Màu nền", ["white", "dark"], key=f"{prefix}_background")
    with cols[2]:
        transition_effect = st.selectbox("Hiệu ứng chuyển cảnh", ["crossfade", "fade", "slide", "none"], key=f"{prefix}_transition")
    with cols[3]:
        transition_duration = st.number_input(
            "Thời gian chuyển cảnh (giây)", min_value=0.0, max_value=5.0, value=0.8, step=0.1, key=f"{prefix}_transition_duration"
        )
    with cols[4]:
        render_scale = st.number_input(
            "Tỉ lệ Render PDF", min_value=1.0, max_value=6.0, value=3.0, step=0.5, key=f"{prefix}_render_scale"
        )

    wm_enabled = st.checkbox("Đóng dấu (Watermark)", value=False, key=f"{prefix}_wm_enabled")
    wm_cols = st.columns(6)
    with wm_cols[0]:
        wm_text = st.text_input("Chữ đóng dấu", key=f"{prefix}_wm_text")
    with wm_cols[1]:
        wm_image = st.file_uploader("Ảnh PNG đóng dấu", type=["png"], key=f"{prefix}_wm_image")
    with wm_cols[2]:
        wm_position = st.selectbox(
            "Vị trí",
            ["dưới-phải", "dưới-trái", "trên-phải", "trên-trái", "giữa"],
            key=f"{prefix}_wm_position",
        )
    with wm_cols[3]:
        wm_opacity = st.slider("Độ mờ", min_value=0.0, max_value=1.0, value=0.35, step=0.05, key=f"{prefix}_wm_opacity")
    with wm_cols[4]:
        wm_size = st.number_input("Kích thước", min_value=8, max_value=800, value=120, step=4, key=f"{prefix}_wm_size")
    with wm_cols[5]:
        wm_margin = st.number_input("Khoảng cách lề", min_value=0, max_value=300, value=32, step=4, key=f"{prefix}_wm_margin")

    watermark_image_path = None
    if wm_image is not None:
        watermark_image_path = save_upload(wm_image, "watermarks")

    watermark_has_content = bool(wm_text or watermark_image_path)
    if wm_enabled and not watermark_has_content:
        st.warning("Đã bật Watermark. Hãy thêm chữ hoặc tải ảnh PNG lên trước khi xuất video.")
    watermark_options = normalize_watermark_options(
        enabled=bool(wm_enabled and watermark_has_content),
        text=wm_text or None,
        image=watermark_image_path,
        position=wm_position,
        opacity=wm_opacity,
        size=int(wm_size),
        margin=int(wm_margin),
    )
    width, height = [int(part) for part in resolution.split("x")]
    return {
        "resolution": (width, height),
        "background": background,
        "transition_effect": transition_effect,
        "transition_duration": float(transition_duration),
        "render_scale": float(render_scale),
        "watermark_options": watermark_options,
    }


st.title("Flyers Video Tool")
single_tab, batch_tab = st.tabs(["Tạo 1 Video", "Xử lý hàng loạt"])

with single_tab:
    left, right = st.columns([0.55, 0.45])
    with left:
        pdf_file = st.file_uploader("File PDF bài thi", type=["pdf"], key="single_pdf")
        audio_file = st.file_uploader("File Audio nghe (MP3)", type=["mp3", "wav", "m4a"], key="single_audio")
        level = st.selectbox("Cấp độ", ["starters", "movers", "flyers"], index=2, key="single_level")
        test_number = st.selectbox("Bài Test số", [1, 2, 3], index=0, key="single_test")
        page_map_upload = st.file_uploader("File cấu hình trang (page_map.json) tuỳ chọn", type=["json"], key="single_page_map")
        range_cols = st.columns(3)
        with range_cols[0]:
            printed_start_page = st.number_input("Trang sách/mục lục bắt đầu Phần 1", min_value=1, value=4, step=1, key="single_printed_start")
        with range_cols[1]:
            ocr_scan_start_page = st.number_input("Trang PDF bắt đầu quét (OCR)", min_value=1, value=1, step=1, key="single_ocr_start")
        with range_cols[2]:
            ocr_scan_end_page = st.number_input("Trang PDF kết thúc quét (OCR)", min_value=1, value=20, step=1, key="single_ocr_end")
        auto_page_map_clicked = st.button("Tự động nhận diện trang PDF (OCR)", use_container_width=True)
        whisper_model = st.text_input("Mô hình Whisper", value="small", key="single_model")
        language = st.text_input("Ngôn ngữ", value="en", key="single_language")

    if page_map_upload is not None:
        page_map_path = save_upload(page_map_upload, "page_maps")
        page_map_config = load_page_map_config(page_map_path)
    else:
        page_map_config = get_preset_page_map(level, test_number)

    if auto_page_map_clicked:
        if pdf_file is None:
            st.warning("Vui lòng tải file PDF lên trước khi nhận diện trang.")
        else:
            try:
                pdf_path = save_upload(pdf_file)
                with st.status("Đang nhận diện trang bằng OCR...", expanded=True) as status:
                    detected_config, warnings, _ocr_results = auto_detect_page_map_from_pdf(
                        pdf_path=pdf_path,
                        output_dir=session_dir() / "ocr",
                        level=level,
                        test_number=test_number,
                        start_page=int(ocr_scan_start_page),
                        end_page=int(ocr_scan_end_page),
                        printed_start_page=int(printed_start_page),
                    )
                    st.session_state.page_map_df = page_map_to_dataframe(detected_config)
                    st.session_state.page_map_level = level
                    st.session_state.page_map_test = test_number
                    detected_json = session_dir() / "detected_page_map.json"
                    export_page_map_config(detected_config, detected_json)
                    for warning in warnings:
                        st.warning(warning)
                    status.update(label="Nhận diện trang hoàn tất", state="complete")
                with detected_json.open("rb") as handle:
                    st.download_button("Download detected_page_map.json", handle, file_name="detected_page_map.json")
            except Exception as exc:
                st.error(str(exc))

    if (
        "page_map_df" not in st.session_state
        or st.session_state.get("page_map_level") != level
        or st.session_state.get("page_map_test") != test_number
        or page_map_upload is not None
    ):
        st.session_state.page_map_df = page_map_to_dataframe(page_map_config)
        st.session_state.page_map_level = level
        st.session_state.page_map_test = test_number

    with right:
        st.subheader("Bản đồ trang PDF (có thể chỉnh sửa)")
        
        current_offset = st.session_state.get("pdf_offset", page_map_config.get("pdf_offset", 0))
        offset_col, recompute_col = st.columns([0.6, 0.4])
        with offset_col:
            new_offset = st.number_input("pdf_offset", value=current_offset, step=1, key="ui_pdf_offset")
        with recompute_col:
            st.write("") # spacer
            st.write("") # spacer
            recompute_clicked = st.button("Tính lại toàn bộ trang PDF theo Độ lệch (Offset)", use_container_width=True)
            
        if recompute_clicked or new_offset != current_offset:
            st.session_state.pdf_offset = new_offset
            df = st.session_state.page_map_df
            for i, row in df.iterrows():
                if not row.get("Khóa trang PDF này", False):
                    printed_str = str(row.get("Số trang sách (in)", ""))
                    printed = [int(p.strip()) for p in printed_str.replace(";", ",").split(",") if p.strip() and p.strip() != "nan"]
                    if printed:
                        df.at[i, "Số trang PDF thực tế"] = ",".join(str(p + new_offset) for p in printed)
            st.session_state.page_map_df = df

        edited_page_map_df = st.data_editor(
            st.session_state.page_map_df,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "Part": st.column_config.NumberColumn("Part", min_value=1, step=1, required=True),
                "Tiêu đề": st.column_config.TextColumn("Tiêu đề", required=True),
                "Số trang sách (in)": st.column_config.TextColumn("Số trang sách (in)", help="Example: 4,5"),
                "Số trang PDF thực tế": st.column_config.TextColumn("Số trang PDF thực tế", help="Example: 7,8"),
                "Bố cục": st.column_config.SelectboxColumn(
                    "Bố cục", options=["single", "side_by_side", "grid", "vertical", "auto"], required=True
                ),
                "Khóa trang PDF này": st.column_config.CheckboxColumn("Khóa trang PDF này", default=False),
            },
        )
        st.session_state.page_map_df = edited_page_map_df

    active_page_map_config = page_map_dataframe_to_config(
        st.session_state.page_map_df, 
        level, 
        test_number, 
        pdf_offset=st.session_state.get("pdf_offset", page_map_config.get("pdf_offset"))
    )

    if "timestamp_df" not in st.session_state:
        st.session_state.timestamp_df = rows_to_dataframe(default_rows_for_page_map(active_page_map_config))

    controls = st.columns(3)
    with controls[0]:
        detect_clicked = st.button("Tự động nhận diện thời gian (Timestamps)", type="primary", use_container_width=True)
    with controls[1]:
        reset_clicked = st.button("Đặt lại bảng", use_container_width=True)
    with controls[2]:
        csv_upload = st.file_uploader("Tải lên file CSV thời gian", type=["csv"], label_visibility="collapsed")

    if reset_clicked:
        st.session_state.timestamp_df = rows_to_dataframe(default_rows_for_page_map(active_page_map_config))

    if csv_upload is not None:
        csv_path = save_upload(csv_upload, "csv")
        st.session_state.timestamp_df = rows_to_dataframe(parse_timestamps_csv(csv_path))

    if detect_clicked:
        if pdf_file is None or audio_file is None:
            st.warning("Vui lòng tải lên cả file PDF và Audio trước khi nhận diện thời gian.")
        else:
            audio_path = save_upload(audio_file)
            with st.status("Đang nhận diện thời gian bằng AI Whisper...", expanded=True) as status:
                duration = get_audio_duration(audio_path)
                segments = transcribe_audio(audio_path, whisper_model=whisper_model, language=language)
                rows, warnings = detect_part_timestamps(
                    segments,
                    duration,
                    test_number=test_number,
                    page_map_config=active_page_map_config,
                )
                detected_csv = session_dir() / "detected_timestamps.csv"
                export_detected_timestamps(rows, detected_csv)
                st.session_state.timestamp_df = rows_to_dataframe(rows)
                for warning in warnings:
                    st.warning(warning)
                status.update(label="Nhận diện thời gian hoàn tất", state="complete")
            with detected_csv.open("rb") as handle:
                st.download_button("Download detected_timestamps.csv", handle, file_name="detected_timestamps.csv")

    st.subheader("Bảng thời gian (Timestamps)")
    edited_df = st.data_editor(
        st.session_state.timestamp_df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "title": st.column_config.TextColumn("title", required=True),
            "start": st.column_config.TextColumn("start", help="MM:SS or HH:MM:SS"),
            "end": st.column_config.TextColumn("end", help="MM:SS or HH:MM:SS"),
            "pdf_pages": st.column_config.TextColumn("pdf_pages", help="Example: 7,8"),
            "layout": st.column_config.SelectboxColumn(
                "layout", options=["single", "side_by_side", "grid", "vertical", "auto"], required=True
            ),
        },
    )
    st.session_state.timestamp_df = edited_df

    st.subheader("Xuất Video")
    single_options = shared_render_options("single")
    open_book_gap = st.number_input("Khoảng trống giữa 2 trang sách", min_value=0, max_value=200, value=24, step=2, key="single_gap")
    output_name = st.text_input("Tên file xuất ra", value=f"{level}_test_{test_number}.mp4")
    if st.button("Xuất Video", type="primary"):
        if pdf_file is None or audio_file is None:
            st.warning("Vui lòng tải lên cả file PDF và Audio trước khi xuất video.")
        else:
            try:
                pdf_path = save_upload(pdf_file)
                audio_path = save_upload(audio_file)
                rows = dataframe_to_rows(edited_df)
                output_path = session_dir() / output_name
                with st.status("Đang xuất video...", expanded=True) as status:
                    create_video(
                        pdf_path=pdf_path,
                        audio_path=audio_path,
                        timestamp_rows=rows,
                        output_path=output_path,
                        open_book_gap=int(open_book_gap),
                        **single_options,
                    )
                    status.update(label="Xuất video thành công", state="complete")
                with output_path.open("rb") as handle:
                    st.download_button("Download MP4", handle, file_name=output_path.name, mime="video/mp4")
                st.video(str(output_path))
            except Exception as exc:
                st.error(str(exc))

with batch_tab:
    st.subheader("Cấu hình hàng loạt")
    source = st.radio("Nguồn dữ liệu", ["Tải lên nhiều file", "Đường dẫn thư mục trên máy tính"], horizontal=True)
    folder_path = None
    pdf_paths = []
    audio_paths = []
    if source == "Tải lên nhiều file":
        pdf_uploads = st.file_uploader("Các file PDF", type=["pdf"], accept_multiple_files=True, key="batch_pdfs")
        audio_uploads = st.file_uploader(
            "Các file Audio", type=["mp3", "wav", "m4a", "aac", "flac", "ogg"], accept_multiple_files=True, key="batch_audios"
        )
        page_map_uploads = st.file_uploader(
            "Các file cấu hình trang (page_map.json)", type=["json"], accept_multiple_files=True, key="batch_page_maps"
        )
        pdf_paths = [save_upload(file, "batch_uploads") for file in pdf_uploads]
        audio_paths = [save_upload(file, "batch_uploads") for file in audio_uploads]
        for file in page_map_uploads:
            save_upload(file, "batch_uploads")
    else:
        folder_path = st.text_input("Đường dẫn thư mục chứa các file PDF/Audio tương ứng")

    pairing_upload = st.file_uploader("File ghép cặp (pairing.csv) tuỳ chọn", type=["csv"], key="batch_pairing_csv")
    batch_level = st.selectbox("Cấp độ mặc định", ["starters", "movers", "flyers"], index=2, key="batch_level")
    batch_test = st.selectbox("Bài Test mặc định", [1, 2, 3], index=0, key="batch_test")
    batch_page_map_upload = st.file_uploader("File page_map.json mặc định tuỳ chọn", type=["json"], key="batch_default_page_map")
    batch_auto_page_map = st.checkbox("Tự động nhận diện trang cho từng PDF", value=False, key="batch_auto_page_map")
    batch_range_cols = st.columns(3)
    with batch_range_cols[0]:
        batch_printed_start = st.number_input("Trang sách/mục lục bắt đầu Phần 1", min_value=1, value=4, step=1, key="batch_printed_start")
    with batch_range_cols[1]:
        batch_ocr_start = st.number_input("Trang PDF bắt đầu quét (Batch OCR)", min_value=1, value=1, step=1, key="batch_ocr_start")
    with batch_range_cols[2]:
        batch_ocr_end = st.number_input("Trang PDF kết thúc quét (Batch OCR)", min_value=1, value=20, step=1, key="batch_ocr_end")
    infer_test = st.checkbox("Tự suy luận số Test từ tên file", value=True)
    csv_only = st.checkbox("Chỉ tạo file CSV (không xuất Video)", value=False, key="batch_csv_only")
    overwrite = st.checkbox("Ghi đè nếu đã có file MP4", value=False, key="batch_overwrite")
    batch_model = st.text_input("Mô hình Whisper", value="small", key="batch_model")
    batch_language = st.text_input("Ngôn ngữ", value="en", key="batch_language")
    output_dir = session_dir() / "batch_outputs"
    batch_options = shared_render_options("batch")
    batch_gap = st.number_input("Khoảng trống giữa 2 trang sách", min_value=0, max_value=200, value=24, step=2, key="batch_gap")

    if st.button("Kiểm tra ghép nối file", use_container_width=True):
        try:
            if pairing_upload is not None:
                pairing_path = save_upload(pairing_upload, "batch_uploads")
                pairs = read_pairing_csv(pairing_path, output_dir=output_dir)
                warnings = []
            else:
                pairs, warnings = discover_batch_pairs(
                    input_dir=folder_path or None,
                    pdfs=pdf_paths,
                    audios=audio_paths,
                    output_dir=output_dir,
                )
            st.session_state.batch_pairs = pairs
            st.session_state.batch_warnings = warnings
        except Exception as exc:
            st.error(str(exc))

    if "batch_warnings" in st.session_state:
        for warning in st.session_state.batch_warnings:
            st.warning(warning)
    if "batch_pairs" in st.session_state:
        pairs = st.session_state.batch_pairs
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "base_name": pair["base_name"],
                        "pdf": Path(pair["pdf_path"]).name,
                        "audio": Path(pair["audio_path"]).name,
                        "status": pair["status"],
                        "level": pair.get("level", batch_level),
                        "test": infer_test_number_from_name(pair["base_name"], batch_test) if infer_test else batch_test,
                        "page_map": Path(pair["page_map_path"]).name if pair.get("page_map_path") else "",
                    }
                    for pair in pairs
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )

        if st.button("Bắt đầu xử lý hàng loạt", type="primary", use_container_width=True):
            with st.status("Đang xử lý hàng loạt...", expanded=True) as status:
                batch_page_map_config = None
                if batch_page_map_upload is not None:
                    batch_page_map_config = load_page_map_config(save_upload(batch_page_map_upload, "batch_uploads"))
                results = process_batch(
                    pairs,
                    level=batch_level,
                    test_number=batch_test,
                    infer_test_number=infer_test,
                    whisper_model=batch_model,
                    language=batch_language,
                    open_book_gap=int(batch_gap),
                    detected_csv_dir=output_dir,
                    csv_only=csv_only,
                    overwrite=overwrite,
                    batch_report=output_dir / "batch_report.csv",
                    page_map_config=batch_page_map_config,
                    auto_page_map=batch_auto_page_map,
                    printed_start_page=int(batch_printed_start),
                    ocr_start_page=int(batch_ocr_start),
                    ocr_end_page=int(batch_ocr_end),
                    **batch_options,
                )
                st.session_state.batch_results = results
                status.update(label="Xử lý hàng loạt hoàn tất", state="complete")

    if "batch_results" in st.session_state:
        results = st.session_state.batch_results
        st.subheader("Trạng thái xử lý hàng loạt")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "base_name": result["base_name"],
                        "status": result["status"],
                        "output": Path(result["output_path"]).name,
                        "error": result.get("error", ""),
                    }
                    for result in results
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
        for result in results:
            output_path = Path(result["output_path"])
            if result["status"] == "exported" and output_path.exists():
                with output_path.open("rb") as handle:
                    st.download_button(
                        f"Download {output_path.name}",
                        handle,
                        file_name=output_path.name,
                        mime="video/mp4",
                    )
        report_path = output_dir / "batch_report.csv"
        if report_path.exists():
            with report_path.open("rb") as handle:
                st.download_button("Download batch_report.csv", handle, file_name="batch_report.csv", mime="text/csv")
