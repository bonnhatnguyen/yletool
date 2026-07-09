import json
import logging
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime

LOGGER = logging.getLogger(__name__)

HISTORY_FILE_NAME = "export_history.json"
OUTPUTS_DIR_NAME = "outputs"

def get_outputs_dir() -> Path:
    """
    Returns the persistent outputs directory.
    Uses flyers_video_tool/outputs relative to the package root.
    """
    base_dir = Path(__file__).parent / OUTPUTS_DIR_NAME
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir

def get_history_file_path() -> Path:
    return get_outputs_dir() / HISTORY_FILE_NAME

def get_date_dir() -> Path:
    date_str = datetime.now().strftime("%Y-%m-%d")
    date_dir = get_outputs_dir() / date_str
    date_dir.mkdir(parents=True, exist_ok=True)
    return date_dir

def load_export_history() -> List[Dict[str, Any]]:
    history_file = get_history_file_path()
    if not history_file.exists():
        return []
    try:
        content = history_file.read_text(encoding="utf-8")
        if not content.strip():
            return []
        return json.loads(content)
    except Exception as e:
        LOGGER.error(f"Error loading export history: {e}")
        return []

def save_export_history(history: List[Dict[str, Any]]) -> None:
    history_file = get_history_file_path()
    try:
        history_file.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        LOGGER.error(f"Error saving export history: {e}")

def register_export(
    output_path: Path,
    input_pdf_name: str,
    input_audio_name: str,
    audio_duration: float,
    output_duration: float,
    level: str,
    test_number: int,
    export_mode: str,
    fps: int,
    resolution: str,
    status: str = "success"
) -> Dict[str, Any]:
    history = load_export_history()
    
    entry = {
        "export_id": datetime.now().strftime("%Y%m%d_%H%M%S_%f"),
        "created_at": datetime.now().isoformat(),
        "output_path": str(output_path),
        "filename": output_path.name,
        "input_pdf_name": input_pdf_name,
        "input_audio_name": input_audio_name,
        "audio_duration": audio_duration,
        "output_duration": output_duration,
        "level": level,
        "test_number": test_number,
        "export_mode": export_mode,
        "fps": fps,
        "resolution": resolution,
        "status": status
    }
    
    # Prepend new entry
    history.insert(0, entry)
    save_export_history(history)
    return entry

def delete_export(export_id: str) -> bool:
    history = load_export_history()
    for i, entry in enumerate(history):
        if entry.get("export_id") == export_id:
            # Try to delete file
            try:
                if entry.get("output_path"):
                    p = Path(entry["output_path"])
                    if p.exists():
                        p.unlink()
            except Exception as e:
                LOGGER.error(f"Failed to delete video file for {export_id}: {e}")
            
            history.pop(i)
            save_export_history(history)
            return True
    return False

def clear_all_exports() -> int:
    history = load_export_history()
    count = 0
    for entry in history:
        try:
            if entry.get("output_path"):
                p = Path(entry["output_path"])
                if p.exists():
                    p.unlink()
            count += 1
        except Exception:
            pass
    save_export_history([])
    return count

def generate_unique_filename(base_name: str, ext: str = ".mp4") -> Path:
    date_dir = get_date_dir()
    
    # Strip extension from base_name if present
    if base_name.endswith(ext):
        base_name = base_name[:-len(ext)]
        
    date_time_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate_name = f"{base_name}_{date_time_str}{ext}"
    candidate_path = date_dir / candidate_name
    
    # In case it somehow exists (e.g., fast batch), append a counter
    counter = 1
    while candidate_path.exists():
        counter += 1
        candidate_name = f"{base_name}_{date_time_str}_v{counter}{ext}"
        candidate_path = date_dir / candidate_name
        
    return candidate_path
