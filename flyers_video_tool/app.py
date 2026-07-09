import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st
try:
    from history import load_export_history, delete_export, clear_all_exports, generate_unique_filename, register_export
except ImportError:
    from flyers_video_tool.history import load_export_history, delete_export, clear_all_exports, generate_unique_filename, register_export

try:
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
        normalize_page_map_config,
        normalize_watermark_options,
        parse_timestamps_csv,
        process_batch,
        read_pairing_csv,
        transcribe_audio,
        SUPPORTED_TIMESTAMP_PROVIDERS,
        detect_timestamps_from_audio_provider
    )
except ImportError:
    from flyers_video_tool.flyers_video_tool import (
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
        normalize_page_map_config,
        normalize_watermark_options,
        parse_timestamps_csv,
        process_batch,
        read_pairing_csv,
        transcribe_audio,
        SUPPORTED_TIMESTAMP_PROVIDERS,
        detect_timestamps_from_audio_provider
    )


st.set_page_config(page_title="YLE Listening Video Tool", layout="wide")


def render_history_ui():
    st.header("Lịch sử Video đã xuất")
    
    if "export_history" not in st.session_state:
        st.session_state.export_history = load_export_history()
        
    history = st.session_state.export_history
    if not history:
        st.info("Chưa có video nào được xuất thành công.")
        return
        
    if st.button("Xóa tất cả video đã xuất"):
        count = clear_all_exports()
        st.success(f"Đã xóa {count} video.")
        st.session_state.export_history = load_export_history()
        st.rerun()
        
    for entry in history:
        with st.container(border=True):
            cols = st.columns([1, 2])
            with cols[0]:
                if entry.get("status") == "success" and Path(entry.get("output_path", "")).exists():
                    st.video(entry["output_path"])
                else:
                    st.warning("File không tồn tại hoặc lỗi xuất.")
            with cols[1]:
                st.subheader(entry.get("filename", "Unknown"))
                st.write(f"**Ngày tạo**: {entry.get('created_at', 'N/A')}")
                st.write(f"**Độ dài**: Audio {entry.get('audio_duration', 0)}s -> Video {entry.get('output_duration', 0)}s")
                st.write(f"**Cấu hình**: {entry.get('export_mode')} | {entry.get('fps')} fps | {entry.get('resolution')}")
                
                action_cols = st.columns(2)
                with action_cols[0]:
                    if entry.get("status") == "success" and Path(entry.get("output_path", "")).exists():
                        with open(entry["output_path"], "rb") as f:
                            st.download_button(
                                "Download MP4",
                                f,
                                file_name=entry["filename"],
                                mime="video/mp4",
                                key=f"dl_{entry['export_id']}",
                                use_container_width=True
                            )
                with action_cols[1]:
                    if st.button("Xóa", key=f"del_{entry['export_id']}", use_container_width=True):
                        delete_export(entry["export_id"])
                        st.session_state.export_history = load_export_history()
                        st.rerun()





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


def clean_timestamp_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df_clean = df.copy()
    
    required_cols = ["title", "start", "end", "pdf_pages", "layout"]
    for col in required_cols:
        if col not in df_clean.columns:
            df_clean[col] = ""
            
    for col in required_cols:
        df_clean[col] = df_clean[col].astype(str).str.strip()
        df_clean.loc[df_clean[col].isin(["nan", "None", ""]), col] = None
        
    df_clean = df_clean.dropna(subset=["title", "start", "end", "pdf_pages"], how="all")
    
    for _, row in df_clean.iterrows():
        title = row.get("title")
        title_str = title if pd.notna(title) else "không tên"
            
        missing = []
        if pd.isna(row.get("start")):
            missing.append("start")
        if pd.isna(row.get("end")):
            missing.append("end")
        if pd.isna(row.get("pdf_pages")):
            missing.append("pdf_pages")
            
        if missing:
            raise ValueError(f"Dòng {title_str} thiếu {'/'.join(missing)}.")
            
    df_clean = df_clean.fillna("")
    return df_clean

def dataframe_to_rows(dataframe: pd.DataFrame):
    cleaned_df = clean_timestamp_dataframe(dataframe)
    if cleaned_df.empty:
        raise ValueError("Bảng thời gian đang trống. Hãy bấm Tự nhận diện đề + thời gian hoặc nhập thời gian thủ công.")
    csv_path = session_dir() / "edited_timestamps.csv"
    cleaned_df[["title", "start", "end", "pdf_pages", "layout"]].to_csv(csv_path, index=False)
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


def shared_render_options(prefix: str, in_expander: bool = True):
    from contextlib import nullcontext
    context = st.expander("Cài đặt Video & Đóng dấu (Nâng cao)") if in_expander else nullcontext()
    with context:
        st.subheader("Tuỳ chỉnh Render")
        
        # UI controls for background
        bg_cols = st.columns([1, 1, 1])
        with bg_cols[0]:
            resolution = st.selectbox("Độ phân giải", ["1280x720", "1920x1080", "3840x2160"], index=0, key=f"{prefix}_resolution")
        with bg_cols[1]:
            bg_mode = st.selectbox("Loại nền", ["Ảnh nền mặc định", "Nền màu trơn", "Ảnh nền tải lên"], key=f"{prefix}_bg_mode")
        
        # Handle background modes
        background_value = "white"
        if bg_mode == "Nền màu trơn":
            background_value = st.selectbox("Màu nền", ["white", "dark"], key=f"{prefix}_bg_color")
        elif bg_mode == "Ảnh nền tải lên":
            uploaded_bg = st.file_uploader("Upload ảnh nền", type=["png", "jpg", "jpeg"], key=f"{prefix}_bg_upload")
            if uploaded_bg:
                background_value = str(save_upload(uploaded_bg, "backgrounds"))
            else:
                background_value = "white" # Fallback if not uploaded
        elif bg_mode == "Ảnh nền mặc định":
            from pathlib import Path
            default_bg_path = Path(__file__).parent / "assets" / "default_background.jpg"
            if default_bg_path.exists():
                background_value = str(default_bg_path)
            else:
                st.warning("Không tìm thấy ảnh nền mặc định.")
                background_value = "white"
                
        with bg_cols[2]:
            render_scale = st.number_input(
                "Tỉ lệ Render PDF", min_value=1.0, max_value=6.0, value=3.0, step=0.5, key=f"{prefix}_render_scale"
            )

        st.subheader("Cài đặt Đóng dấu (Watermark)")
        from pathlib import Path
        from PIL import Image, UnidentifiedImageError
        
        # Check both jpg and png
        default_logo_path = None
        for ext in ["png", "jpg", "jpeg"]:
            p = Path(__file__).parent / "assets" / f"default_logo.{ext}"
            if p.exists():
                default_logo_path = p
                break
        
        has_default_logo = False
        default_logo_invalid = False
        if default_logo_path:
            try:
                with Image.open(default_logo_path) as img:
                    img.verify()
                has_default_logo = True
            except Exception:
                default_logo_invalid = True
                
        wm_enabled = st.checkbox("Đóng dấu (Watermark)", value=has_default_logo, key=f"{prefix}_wm_enabled")
        
        if default_logo_invalid:
            st.warning("Default logo không hợp lệ. Vui lòng upload watermark khác.")
        elif not wm_enabled and has_default_logo:
            st.info("Watermark đang tắt. Bật mục Đóng dấu nếu muốn logo xuất hiện trong video.")
        
        if f"{prefix}_vertical_position" not in st.session_state:
            st.session_state[f"{prefix}_vertical_position"] = "bottom"
            st.session_state[f"{prefix}_horizontal_position"] = "center"
            
        wm_cols1 = st.columns(2)
        with wm_cols1[0]:
            wm_text = st.text_input("Chữ đóng dấu", key=f"{prefix}_wm_text")
        with wm_cols1[1]:
            wm_image = st.file_uploader("Ảnh đóng dấu", type=["png", "jpg", "jpeg"], key=f"{prefix}_wm_image")
            
        wm_cols2 = st.columns(3)
        with wm_cols2[0]:
            wm_opacity = st.slider("Độ mờ", min_value=0.0, max_value=1.0, value=0.35, step=0.05, key=f"{prefix}_wm_opacity")
        with wm_cols2[1]:
            wm_size = st.number_input("Kích thước", min_value=8, max_value=800, value=120, step=4, key=f"{prefix}_wm_size")
        with wm_cols2[2]:
            wm_margin = st.number_input("Khoảng cách lề", min_value=0, max_value=300, value=32, step=4, key=f"{prefix}_wm_margin")

        st.write("Vị trí Đóng dấu:")
        grid_col1, grid_col2, grid_col3, _ = st.columns([1, 1, 1, 3])
        with grid_col1:
            if st.button("↖ Trên trái", key=f"{prefix}_tl", use_container_width=True):
                st.session_state[f"{prefix}_vertical_position"] = "top"
                st.session_state[f"{prefix}_horizontal_position"] = "left"
            if st.button("← Giữa trái", key=f"{prefix}_ml", use_container_width=True):
                st.session_state[f"{prefix}_vertical_position"] = "center"
                st.session_state[f"{prefix}_horizontal_position"] = "left"
            if st.button("↙ Dưới trái", key=f"{prefix}_bl", use_container_width=True):
                st.session_state[f"{prefix}_vertical_position"] = "bottom"
                st.session_state[f"{prefix}_horizontal_position"] = "left"
        with grid_col2:
            if st.button("↑ Trên giữa", key=f"{prefix}_tc", use_container_width=True):
                st.session_state[f"{prefix}_vertical_position"] = "top"
                st.session_state[f"{prefix}_horizontal_position"] = "center"
            if st.button("· Chính giữa", key=f"{prefix}_cc", use_container_width=True):
                st.session_state[f"{prefix}_vertical_position"] = "center"
                st.session_state[f"{prefix}_horizontal_position"] = "center"
            if st.button("↓ Dưới giữa", key=f"{prefix}_bc", use_container_width=True):
                st.session_state[f"{prefix}_vertical_position"] = "bottom"
                st.session_state[f"{prefix}_horizontal_position"] = "center"
        with grid_col3:
            if st.button("↗ Trên phải", key=f"{prefix}_tr", use_container_width=True):
                st.session_state[f"{prefix}_vertical_position"] = "top"
                st.session_state[f"{prefix}_horizontal_position"] = "right"
            if st.button("→ Giữa phải", key=f"{prefix}_mr", use_container_width=True):
                st.session_state[f"{prefix}_vertical_position"] = "center"
                st.session_state[f"{prefix}_horizontal_position"] = "right"
            if st.button("↘ Dưới phải", key=f"{prefix}_br", use_container_width=True):
                st.session_state[f"{prefix}_vertical_position"] = "bottom"
                st.session_state[f"{prefix}_horizontal_position"] = "right"
                
        vert_pos = st.session_state[f"{prefix}_vertical_position"]
        horiz_pos = st.session_state[f"{prefix}_horizontal_position"]
        st.write(f"Vị trí đang chọn: **{vert_pos} - {horiz_pos}**")
        
        watermark_has_content = bool(wm_text or wm_image or has_default_logo)
        
        final_wm_image = None
        if wm_image:
            final_wm_image = str(save_upload(wm_image, "watermarks"))
        elif has_default_logo:
            final_wm_image = str(default_logo_path)
            
        watermark_options = {
            "enabled": bool(wm_enabled and watermark_has_content),
            "text": wm_text.strip() if wm_text else None,
            "image": final_wm_image,
            "opacity": wm_opacity,
            "size": int(wm_size),
            "margin": int(wm_margin),
            "position": f"{vert_pos}-{horiz_pos}"
        }
        
        # True Preview rendering
        st.write("---")
        if st.button("Xem trước đúng như file xuất", key=f"{prefix}_preview_btn", use_container_width=True):
            with st.spinner("Đang render bản xem trước..."):
                from flyers_video_tool import generate_preview_scene
                # Try to get real pdf pages if any available in state
                pdf_pages = []
                if "pdf_pages" in st.session_state:
                    pdf_pages = st.session_state.pdf_pages
                
                # Render using the real backend logic
                res_w, res_h = map(int, resolution.split("x"))
                try:
                    preview_data = generate_preview_scene(
                        pdf_pages=pdf_pages[:2] if pdf_pages else [], # use up to 2 pages
                        layout="auto",
                        resolution=(res_w, res_h),
                        background=background_value,
                        watermark_options=watermark_options,
                        open_book_gap=24
                    )
                    
                    st.image(preview_data["image"], use_column_width=True)
                    
                    if watermark_options["enabled"] and preview_data["watermark_box"]:
                        box = preview_data["watermark_box"]
                        st.info(f"**Thông số Render Thực Tế**\n\n"
                                f"Độ phân giải: {res_w}x{res_h}\n\n"
                                f"Nền: {bg_mode}\n\n"
                                f"Watermark box: X={box['x']}, Y={box['y']}, Width={box['width']}, Height={box['height']}")
                except Exception as e:
                    st.error(f"Lỗi khi render xem trước: {e}")

    return {
        "export_mode": "fast_static",
        "fps": 1,
        "resolution": resolution,
        "background": background_value,
        "transition_effect": "none",
        "transition_duration": 0.0,
        "render_scale": render_scale,
        "watermark_options": watermark_options
    }

st.title("YLE Listening Video Tool")

app_mode = st.sidebar.radio("CHẾ ĐỘ HOẠT ĐỘNG", ["Tạo 1 Video", "Xử lý hàng loạt"])

if app_mode == "Tạo 1 Video":
    st.header("Bước 1: Tải lên & Cấu hình")
    col1, col2 = st.columns(2)
    with col1:
        pdf_file = st.file_uploader("File PDF bài thi", type=["pdf"], key="single_pdf")
        level = st.selectbox("Cấp độ", ["starters", "movers", "flyers"], index=2, key="single_level")
    with col2:
        audio_file = st.file_uploader("File Audio nghe (MP3)", type=["mp3", "wav", "m4a"], key="single_audio")
        test_number = st.selectbox("Bài Test số", [1, 2, 3], index=0, key="single_test")
        
    with st.expander("Cài đặt nâng cao (Nhận diện)"):
        page_map_upload = st.file_uploader("File cấu hình trang (page_map.json) tuỳ chọn", type=["json"], key="single_page_map")
        range_cols = st.columns(3)
        with range_cols[0]:
            printed_start_page = st.number_input("Trang sách/mục lục bắt đầu Phần 1", min_value=1, value=4, step=1, key="single_printed_start")
        with range_cols[1]:
            ocr_scan_start_page = st.number_input("Trang PDF bắt đầu quét (OCR)", min_value=1, value=1, step=1, key="single_ocr_start")
        with range_cols[2]:
            ocr_scan_end_page = st.number_input("Trang PDF kết thúc quét (OCR)", min_value=1, value=20, step=1, key="single_ocr_end")
        
        provider = st.selectbox("Công cụ nhận diện thời gian", ["auto", "gemini", "whisper"], index=0, key="single_provider")
        st.caption("Gemini cần có mạng và sẽ tải audio lên máy chủ Google. Whisper chạy trên máy (cần cấu hình mạnh).")
        gemini_models_input = st.text_input("Danh sách mô hình Gemini (cách nhau bởi dấu phẩy)", value="gemini-2.5-flash-lite,gemini-3.1-flash-lite,gemini-2.5-flash,gemini-3-flash-preview,gemini-3.5-flash,gemini-2.5-pro,gemini-3.1-pro-preview", key="single_gemini_models")
        whisper_model = st.text_input("Mô hình Whisper", value="small", key="single_model")
        language = st.text_input("Ngôn ngữ Whisper", value="en", key="single_language")

    st.header("Bước 2: Tự động nhận diện")
    detect_clicked = st.button("Tự nhận diện đề + thời gian", type="primary", width='stretch')

    if page_map_upload is not None:
        page_map_path = save_upload(page_map_upload, "page_maps")
        page_map_config = load_page_map_config(page_map_path)
    else:
        page_map_config = get_preset_page_map(level, test_number)
        if page_map_config.get("parts"):
            calc_offset = page_map_config["parts"][0]["pages"][0] - int(printed_start_page)
            page_map_config["pdf_offset"] = calc_offset
            page_map_config = normalize_page_map_config(page_map_config)

    if (
        "page_map_df" not in st.session_state
        or st.session_state.get("page_map_level") != level
        or st.session_state.get("page_map_test") != test_number
        or page_map_upload is not None
    ):
        st.session_state.page_map_df = page_map_to_dataframe(page_map_config)
        st.session_state.page_map_level = level
        st.session_state.page_map_test = test_number

    if detect_clicked:
        if pdf_file is None or audio_file is None:
            st.warning("Vui lòng tải lên cả file PDF và Audio ở Bước 1 trước khi tự động nhận diện.")
        else:
            try:
                pdf_path = save_upload(pdf_file)
                audio_path = save_upload(audio_file)
                
                with st.status("1/2 Đang nhận diện bản đồ trang PDF (OCR)...", expanded=True) as status_ocr:
                    detected_config, warnings_ocr, _ = auto_detect_page_map_from_pdf(
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
                    for warning in warnings_ocr:
                        st.warning(warning)
                    status_ocr.update(label="Nhận diện bản đồ trang hoàn tất", state="complete")
                    
                with st.status(f"2/2 Đang nhận diện thời gian ({provider})...", expanded=True) as status_time:
                    rows, warnings_time = detect_timestamps_from_audio_provider(
                        audio_path=audio_path,
                        page_map_config=detected_config,
                        provider=provider,
                        whisper_model=whisper_model,
                        language=language,
                        gemini_models_input=gemini_models_input,
                    )
                    detected_csv = session_dir() / "detected_timestamps.csv"
                    export_detected_timestamps(rows, detected_csv)
                    st.session_state.timestamp_df = rows_to_dataframe(rows)
                    st.session_state.timestamps_detected = True
                    st.session_state.page_map_changed_since_timestamp = False
                    for warning in warnings_time:
                        st.warning(warning)
                    status_time.update(label="Nhận diện thời gian hoàn tất", state="complete")
                    
            except Exception as exc:
                st.error(str(exc))

    st.header("Bước 3: Xem lại và Chỉnh sửa")
    
    # Calculate active page map
    active_page_map_config = page_map_dataframe_to_config(
        st.session_state.page_map_df, 
        level, 
        test_number, 
        pdf_offset=st.session_state.get("pdf_offset", page_map_config.get("pdf_offset"))
    )

    if "timestamp_df" not in st.session_state:
        st.session_state.timestamp_df = rows_to_dataframe(default_rows_for_page_map(active_page_map_config))
        st.session_state.timestamps_detected = False

    st.subheader("Bảng thời gian & Trang (Rút gọn)")
    
    # Show merged simplified table
    merged_df = st.session_state.timestamp_df.copy()
    
    # We will map "pdf_pages" into merged_df if we want to show it.
    # Actually just show timestamp_df and page_map_df in advanced.
    # For now, let's keep timestamp_df but format it simply.
    
    st.data_editor(
        st.session_state.timestamp_df,
        num_rows="dynamic",
        width='stretch',
        column_config={
            "title": st.column_config.TextColumn("Part", required=True),
            "start": st.column_config.TextColumn("Bắt đầu", help="MM:SS"),
            "end": st.column_config.TextColumn("Kết thúc", help="MM:SS"),
            "pdf_pages": st.column_config.TextColumn("Trang PDF"),
            "layout": None, # Hide layout
        },
        disabled=True # Basic mode is view only, editing is in advanced or manual upload
    )
    
    if not st.session_state.get("timestamps_detected", False):
        st.warning("Đây là các mốc thời gian mẫu (placeholder). Hãy chạy 'Tự nhận diện đề + thời gian' trước khi xuất video.")

    with st.expander("Chỉnh sửa dữ liệu thủ công (Nâng cao)"):
        st.write("Cấu hình Bản đồ trang PDF:")
        current_offset = st.session_state.get("pdf_offset", page_map_config.get("pdf_offset", 0))
        new_offset = st.number_input("Độ lệch (pdf_offset)", value=current_offset, step=1, key="ui_pdf_offset")
        if new_offset != current_offset:
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
            width='stretch',
            key="advanced_page_map_editor"
        )
        if not st.session_state.page_map_df.equals(edited_page_map_df):
            st.session_state.page_map_changed_since_timestamp = True
        st.session_state.page_map_df = edited_page_map_df
        
        st.write("Bảng thời gian chi tiết:")
        csv_upload = st.file_uploader("Tải lên file CSV thời gian", type=["csv"])
        if csv_upload is not None:
            csv_path = save_upload(csv_upload, "csv")
            st.session_state.timestamp_df = rows_to_dataframe(parse_timestamps_csv(csv_path))
            st.session_state.timestamps_detected = True
            
        edited_timestamp_df = st.data_editor(
            st.session_state.timestamp_df,
            num_rows="dynamic",
            width='stretch',
            key="advanced_timestamp_editor"
        )
        st.session_state.timestamp_df = edited_timestamp_df

    st.header("Bước 4: Xuất Video")
    single_options = shared_render_options("single", in_expander=True)
    open_book_gap = st.number_input("Khoảng trống giữa 2 trang sách", min_value=0, max_value=200, value=24, step=2, key="single_gap")
    output_name = st.text_input("Tên file xuất ra", value=f"{level}_test_{test_number}.mp4")
    user_reviewed = st.checkbox("Tôi đã kiểm tra thời gian thủ công", value=False)
    
    can_export = True
    export_warnings = []
    
    if not st.session_state.get("timestamps_detected", False) and not user_reviewed:
        can_export = False
        export_warnings.append("Vui lòng nhận diện thời gian, upload CSV, hoặc tick 'Tôi đã kiểm tra thời gian thủ công'.")
        
    try:
        rows = dataframe_to_rows(st.session_state.timestamp_df)
        
        for row in rows:
            if row.get("end_seconds", 0) <= row.get("start_seconds", 0):
                can_export = False
                export_warnings.append(f"Phần {row.get('title')} có thời lượng không hợp lệ.")
                break
            if not row.get("pdf_pages"):
                can_export = False
                export_warnings.append(f"Phần {row.get('title')} bị thiếu cấu hình trang PDF.")
                break
    except ValueError as exc:
        rows = []
        can_export = False
        export_warnings.append(f"Bảng thời gian chưa hợp lệ: {exc}")

    if st.session_state.get("page_map_changed_since_timestamp", False) and not user_reviewed:
        can_export = False
        export_warnings.append("Page Map đã thay đổi. Vui lòng đồng bộ hoặc tick 'Tôi đã kiểm tra thời gian thủ công'.")
        
    force_duration = st.checkbox("Tôi hiểu và vẫn muốn xuất video bỏ qua cảnh báo lệch thời gian", value=False)
    if not force_duration and st.session_state.get("audio_duration"):
        last_end = rows[-1].get("end_seconds", 0) if rows else 0
        if abs(st.session_state.audio_duration - last_end) > 5.0:
            can_export = False
            export_warnings.append("Tổng thời gian các Part không khớp audio. Vui lòng nhận diện lại thời gian hoặc đánh dấu bỏ qua cảnh báo.")

    for warn in export_warnings:
        st.warning(warn)

    if st.button("Xuất Video", type="primary", disabled=not can_export):
        if pdf_file is None or audio_file is None:
            st.warning("Vui lòng tải lên cả file PDF và Audio trước khi xuất video.")
        else:
            try:
                pdf_path = save_upload(pdf_file)
                audio_path = save_upload(audio_file)
                try:
                    rows = dataframe_to_rows(st.session_state.timestamp_df)
                except ValueError as exc:
                    st.error(f"Bảng thời gian chưa hợp lệ: {exc}")
                    st.stop()
                    
                persistent_output_path = generate_unique_filename(output_name)
                
                with st.status("Đang xuất video...", expanded=True) as status:
                    from flyers_video_tool import get_audio_duration, get_format_duration
                    create_video(
                        pdf_path=pdf_path,
                        audio_path=audio_path,
                        timestamp_rows=rows,
                        output_path=persistent_output_path,
                        open_book_gap=int(open_book_gap),
                        **single_options,
                    )
                    
                    audio_dur = get_audio_duration(audio_path)
                    video_dur = get_format_duration(persistent_output_path)
                    
                    register_export(
                        output_path=persistent_output_path,
                        input_pdf_name=pdf_file.name,
                        input_audio_name=audio_file.name,
                        audio_duration=audio_dur,
                        output_duration=video_dur,
                        level=level,
                        test_number=test_number,
                        export_mode=single_options["export_mode"],
                        fps=single_options["fps"],
                        resolution=single_options["resolution"]
                    )
                    st.session_state.export_history = load_export_history()
                    status.update(label="Xuất video thành công", state="complete")
                
                st.success(f"Video đã được xuất và lưu thành công tại: {persistent_output_path.name}")
                st.rerun() # Refresh to show in history
            except Exception as exc:
                st.error(str(exc))
                
    render_history_ui()

elif app_mode == "Xử lý hàng loạt":
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
    output_dir = session_dir() / "batch_outputs"
    
    with st.expander("Cài đặt nâng cao (Batch)"):
        batch_page_map_upload = st.file_uploader("File page_map.json mặc định tuỳ chọn", type=["json"], key="batch_default_page_map")
        batch_auto_page_map = st.checkbox("Tự động nhận diện trang cho từng PDF", value=True, key="batch_auto_page_map")
        batch_range_cols = st.columns(3)
        with batch_range_cols[0]:
            batch_printed_start = st.number_input("Trang sách bắt đầu", min_value=1, value=4, step=1, key="batch_printed_start")
        with batch_range_cols[1]:
            batch_ocr_start = st.number_input("Trang PDF quét (Batch OCR) từ", min_value=1, value=1, step=1, key="batch_ocr_start")
        with batch_range_cols[2]:
            batch_ocr_end = st.number_input("Trang PDF kết thúc quét (Batch OCR) đến", min_value=1, value=20, step=1, key="batch_ocr_end")
        infer_test = st.checkbox("Tự suy luận số Test từ tên file", value=True)
        csv_only = st.checkbox("Chỉ tạo file CSV (không xuất Video)", value=False, key="batch_csv_only")
        overwrite = st.checkbox("Ghi đè nếu đã có file MP4", value=False, key="batch_overwrite")
        batch_model = st.text_input("Mô hình Whisper", value="small", key="batch_model")
        batch_language = st.text_input("Ngôn ngữ", value="en", key="batch_language")
        batch_options = shared_render_options("batch", in_expander=False)
        batch_gap = st.number_input("Khoảng trống giữa 2 trang sách", min_value=0, max_value=200, value=24, step=2, key="batch_gap")

    if st.button("Kiểm tra ghép nối file", width='stretch'):
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
            width='stretch',
            hide_index=True,
        )

        if st.button("Bắt đầu xử lý hàng loạt", type="primary", width='stretch'):
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
            width='stretch',
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

    render_history_ui()
