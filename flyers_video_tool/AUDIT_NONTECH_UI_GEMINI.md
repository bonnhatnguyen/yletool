# Audit: Non-technical UI simplification + Gemini timestamp provider

## Current audit summary

The codebase works like a developer tool, but the Streamlit UI is still too technical for a non-technical user. The app currently exposes page-map internals such as `printed_start_page`, OCR scan bounds, `pdf_offset`, editable page-map rows, Whisper model, language, render scale, transition duration, and watermark internals directly in the main flow.

The timestamp detection path is currently faster-whisper only. There is no provider abstraction for Gemini, and `requirements.txt` does not include the Google GenAI SDK.

## Required product direction

Create a beginner-first UI:

### Simple mode default
Use a wizard with only 4 visible steps:

1. Upload files
   - Single mode: Upload PDF + MP3.
   - Batch mode: Upload many PDFs + audios, or select a folder.

2. Auto detect
   - One main button: `Tự nhận diện đề + thời gian`.
   - Internally run page-map OCR and timestamp detection.
   - Choose timestamp provider via a simple selectbox:
     - `Gemini AI (khuyên dùng nếu có mạng)`
     - `Whisper local (không cần mạng)`
   - Default provider should be Gemini if a local API key is configured; otherwise Whisper.

3. Review
   - Show only a simple table:
     - Part
     - Time
     - Pages
     - Status
   - Hide printed pages, PDF pages, pdf_offset, layout, OCR range, render scale, model name, etc. unless Advanced mode is opened.
   - If everything looks valid, show `Sẵn sàng xuất video`.

4. Export
   - One main button: `Xuất video` or `Xuất tất cả video`.
   - Default settings: 1920x1080, white background, crossfade 0.8s, render scale 3.

### Advanced settings collapsed
Move these into `st.expander("Cài đặt nâng cao")`:
- printed_start_page
- ocr_start_page / ocr_end_page
- pdf_offset
- page_map table
- timestamp CSV editor
- Whisper model
- language
- render scale
- transition duration
- layout
- watermark advanced controls

### Disable unsafe export
Do not allow export while timestamps are still placeholders.
The current UI warns about placeholders, but it still allows export. Change this so export is disabled until one of these is true:
- auto timestamp detection succeeded, or
- the user uploaded a CSV, or
- the user explicitly checks `Tôi đã kiểm tra thời gian thủ công`.

### Fix watermark position translation bug
Current app.py uses Vietnamese values for watermark position:
- `dưới-phải`
- `dưới-trái`
- `trên-phải`
- `trên-trái`
- `giữa`

But `normalize_watermark_options` expects:
- `bottom-right`
- `bottom-left`
- `top-right`
- `top-left`
- `center`

Add a mapping layer before calling `normalize_watermark_options`.

## Gemini timestamp provider

### Security requirement
Do not commit a real Gemini API key to GitHub.
The UI must not ask the user to type a key each time, but the key must be stored locally outside git.

Acceptable local key sources, in this priority order:
1. Environment variable: `GEMINI_API_KEY` or `GOOGLE_API_KEY`.
2. Streamlit secrets: `.streamlit/secrets.toml`.
3. Local ignored file: `local_secrets.py` or `.env`, both included in `.gitignore`.

The user should not need to type the key in the UI.

### Required files
- Add `.env.example` with `GEMINI_API_KEY=your_key_here`.
- Add `.streamlit/secrets.toml.example` with `GEMINI_API_KEY="your_key_here"`.
- Add `.env`, `.streamlit/secrets.toml`, and `local_secrets.py` to `.gitignore`.

### Dependencies
Add `google-genai` to requirements.txt.

### Core architecture
Add a provider abstraction:

```python
SUPPORTED_TIMESTAMP_PROVIDERS = {"whisper", "gemini"}

def detect_timestamps_from_audio_provider(
    audio_path,
    page_map_config,
    provider="auto",
    whisper_model="small",
    language="en",
    gemini_model="gemini-3.5-flash",
):
    ...
```

Provider behavior:
- `auto`: use Gemini if API key exists and internet/API call works; otherwise fallback to Whisper.
- `gemini`: use Gemini only. If key missing or API fails, show a clear error and optionally fallback if the UI toggle allows fallback.
- `whisper`: use faster-whisper local only.

### Gemini implementation
Use Gemini audio understanding to analyze uploaded audio. Ask for strict JSON output:

```json
{
  "parts": [
    {"part": 1, "start": "00:00", "confidence": 0.9, "evidence": "Part one"},
    {"part": 2, "start": "05:40", "confidence": 0.8, "evidence": "Part two"}
  ],
  "warnings": []
}
```

Prompt Gemini with the actual configured part count from `page_map_config`. For Starters detect 4 parts; for Movers/Flyers detect 5 parts. Do not hard-code 5.

After Gemini returns part starts:
- Convert starts to seconds.
- End of Part N = start of Part N+1.
- End of final part = audio duration.
- Keep the existing CSV review workflow.
- Always export detected_timestamps.csv.

### Gemini privacy note in UI
Show a small note only when Gemini is selected:
`Gemini cần mạng và sẽ gửi file audio lên Gemini API để nhận diện mốc thời gian. Nếu muốn offline hoàn toàn, chọn Whisper local.`

## Tests to add
1. Unit test provider selection:
   - `auto` chooses Gemini when key exists.
   - `auto` falls back to Whisper when key missing.
2. Unit test parsing Gemini JSON into timestamp rows.
3. Regression test for page-map OCR:
   - Contents page contains both Listening and Reading and Writing.
   - Listening Part 1 starts on PDF page 5.
   - Reading and Writing starts on PDF page 12.
   - Expected Part 5 = [11], not [11,12,13...].
4. UI-level smoke test or manual QA checklist for:
   - Simple single-video flow.
   - Simple batch flow.
   - Watermark enabled with Vietnamese position labels.

## Nontechnical UX acceptance criteria
A nontechnical user should be able to create one video with only:
1. Upload PDF.
2. Upload MP3.
3. Click `Tự nhận diện đề + thời gian`.
4. Click `Xuất video`.

All other controls should be hidden unless Advanced mode is expanded.
