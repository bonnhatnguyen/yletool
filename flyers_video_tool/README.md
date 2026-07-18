# Flyers Video Tool

Tool local-only de tao video bai nghe Cambridge Flyers tu 1 file PDF scan va 1 file audio MP3.

Khong dung Gemini API, OpenAI API hay bat ky API tra phi nao. Timestamp duoc detect bang `faster-whisper` chay local. Lan dau chay model co the tu tai weight open-source ve may; sau do khong can API key.

## Chuc nang

- Render trang PDF bang PyMuPDF thanh anh ro net.
- Ghe ngang 2 trang cho Part 3 va Part 4 theo dang mo sach.
- Detect moc Part 1-5 tu audio bang `faster-whisper`.
- Luon xuat `detected_timestamps.csv` de nguoi dung sua lai neu AI nghe sai.
- Tao MP4 1920x1080 mac dinh, tuy chon 3840x2160.
- Batch processing theo folder hoac nhieu file PDF/MP3.
- Tu match PDF va audio theo cung base filename.
- Dynamic page map cho Starters/Movers/Flyers, khong ep co dinh 5 parts.
- Auto-detect page map tu PDF scan bang OCR local Tesseract.
- Moi Part co layout rieng: `single`, `side_by_side`, `grid`, `vertical`, `auto`.
- Transition giua cac Part: `crossfade`, `fade`, `slide`, hoac `none`.
- Watermark text hoac PNG, tuy chinh vi tri, opacity, size, margin.
- Co CLI va Streamlit UI.

## Cai dat

Tao virtual environment:

```powershell
cd flyers_video_tool
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Cai FFmpeg

MoviePy, pydub va faster-whisper can FFmpeg de doc audio/render video.

Windows:

1. Tai FFmpeg tu https://www.gyan.dev/ffmpeg/builds/ hoac https://ffmpeg.org/download.html
2. Giai nen.
3. Them thu muc `bin` cua FFmpeg vao `PATH`.
4. Mo terminal moi va kiem tra:

```powershell
ffmpeg -version
```

macOS:

```bash
brew install ffmpeg
```

Ubuntu:

```bash
sudo apt update
sudo apt install ffmpeg
```

## Cai Tesseract OCR cho Auto Page Map

Auto Page Map chay local bang Tesseract, khong can API key.

Windows:

1. Cai Tesseract tu https://github.com/UB-Mannheim/tesseract/wiki
2. Them thu muc cai dat, vi du `C:\Program Files\Tesseract-OCR`, vao `PATH`.
3. Mo terminal moi va kiem tra:

```powershell
tesseract --version
```

macOS:

```bash
brew install tesseract
```

Ubuntu:

```bash
sudo apt update
sudo apt install tesseract-ocr
```

## Page map mac dinh

Tool ho tro page map dong bang JSON. Tong so Part duoc lay tu `len(parts)`, khong hard-code 5 parts.

Vi du Flyers:

```json
{
  "level": "flyers",
  "test": 1,
  "pdf_offset": 1,
  "parts": [
    {"part": 1, "title": "Part 1", "printed_pages": [4], "pages": [5], "layout": "single"},
    {"part": 2, "title": "Part 2", "printed_pages": [5], "pages": [6], "layout": "single"},
    {"part": 3, "title": "Part 3", "printed_pages": [6, 7], "pages": [7, 8], "layout": "side_by_side"},
    {"part": 4, "title": "Part 4", "printed_pages": [8, 9], "pages": [9, 10], "layout": "side_by_side"},
    {"part": 5, "title": "Part 5", "printed_pages": [10], "pages": [11], "layout": "single"}
  ]
}
```

Vi du Starters 4 parts nam tai `examples/starters_test1_page_map.json`.

`printed_pages` la so trang in trong sach hoac muc luc, chi de tham khao/hien thi. `pages` la PDF page that, bat dau tu 1, va la gia tri duy nhat dung de render video. Khong duoc gia dinh `printed_pages = pages`; moi PDF co the co offset khac nhau. `pdf_offset = pdf_page_of_part_1 - printed_page_of_part_1` neu biet trang in cua Part 1.

Layout:

- `single`: 1 trang can giua.
- `side_by_side`: 2 trang ghep ngang trai/phai.
- `grid`: 3+ trang theo grid, giu ty le, khong crop.
- `vertical`: xep doc nhieu trang.
- `auto`: 1 trang -> single, 2 trang -> side_by_side, 3+ trang -> grid.

### Auto-detect page map tu PDF

Auto Page Map can gioi han vung quet Listening. Tool khong quet toan bo PDF neu khong co end page, de tranh nhan nham trang muc luc, Reading/Writing, dap an, transcript, hoac Test khac.

Chi detect page map va xuat JSON de sua truoc:

```powershell
python flyers_video_tool.py `
  --pdf "input.pdf" `
  --level starters `
  --test 1 `
  --auto-page-map `
  --page-map-only `
  --page-map-output "detected_page_map.json" `
  --ocr-start-page 5 `
  --ocr-end-page 12 `
  --printed-part1-page 4
```

Co the dung alias:

```powershell
--listening-start-page 5 --listening-end-page 12
```

Detect page map roi tiep tuc auto timestamp/render:

```powershell
python flyers_video_tool.py `
  --pdf "input.pdf" `
  --audio "input.mp3" `
  --output "output.mp4" `
  --level starters `
  --test 1 `
  --auto-page-map `
  --listening-start-page 5 `
  --listening-end-page 12 `
  --auto-timestamp `
  --overwrite
```

Neu OCR khong chac chan, tool van xuat JSON draft va warning. Mo JSON hoac bang page map trong UI de sua truoc khi export.

OCR uu tien text nam o vung dau trang (`heading_text`) va bo qua trang co dau hieu `Transcript`, `Audioscript`, `Answer key`, `Answers`, `Tapescript`. Neu co nhieu trang cung co `Part 1`, `Part 2`, tool chi chon chuoi Part tang dan theo thu tu trang; neu thieu Part se warning de sua thu cong.

Co the dung `--printed-start-page` hoac alias `--printed-part1-page` de tool tinh `pdf_offset` tu PDF page that cua Part 1 sau OCR. Streamlit UI hien thi ca "So trang sach (in)" va "So trang PDF thuc te"; render chi dua tren PDF page that.

Test 1 Listening:

- Part 1 = PDF page 5
- Part 2 = PDF page 6
- Part 3 = PDF pages 7,8
- Part 4 = PDF pages 9,10
- Part 5 = PDF page 11

Test 2 Listening:

- Part 1 = PDF page 23
- Part 2 = PDF page 24
- Part 3 = PDF pages 25,26
- Part 4 = PDF pages 27,28
- Part 5 = PDF page 29

Test 3 Listening:

- Part 1 = PDF page 41
- Part 2 = PDF page 42
- Part 3 = PDF pages 43,44
- Part 4 = PDF pages 45,46
- Part 5 = PDF page 47

PDF page number bat dau tu 1. Trong code PyMuPDF se tu tru 1 khi render.

## Chay CLI voi auto timestamp

```powershell
python flyers_video_tool.py `
  --pdf "Student's Book - Flyers 1 - 2018 (3).pdf" `
  --audio "Flyers 1 TEST 1 - Listening Tests 1 .mp3" `
  --test 1 `
  --level flyers `
  --page-map "examples\flyers_test1_page_map.json" `
  --auto-timestamp `
  --output "output.mp4"
```

Lenh tren se:

1. Transcribe audio bang `faster-whisper` local.
2. Tim cac cum nhu `part one`, `now listen to part two`, `look at part three`.
3. Xuat `detected_timestamps.csv`.
4. Render video MP4.

Mac dinh video co transition `crossfade` 0.8 giay giua cac Part.

Neu chi muon detect CSV de sua truoc:

```powershell
python flyers_video_tool.py `
  --pdf "input.pdf" `
  --audio "input.mp3" `
  --test 1 `
  --auto-timestamp `
  --csv-only `
  --detected-csv "detected_timestamps.csv" `
  --output "draft.mp4"
```

## Chay bang timestamp CSV da sua

```powershell
python flyers_video_tool.py `
  --pdf "input.pdf" `
  --audio "input.mp3" `
  --timestamps "detected_timestamps.csv" `
  --output "output.mp4"
```

Format CSV:

```csv
title,start,end,pdf_pages,layout
Part 1,00:00,05:40,5,single
Part 2,05:40,11:35,6,single
Part 3,11:35,17:25,"7,8",side_by_side
Part 4,17:25,23:05,9,single
```

So dong CSV phu thuoc page map. Starters co the 4 dong, Movers/Flyers thuong 5 dong. File mau nam tai `examples/timestamps_test1_template.csv`.

## Tuy chon CLI

```powershell
python flyers_video_tool.py `
  --pdf "input.pdf" `
  --audio "input.mp3" `
  --test 1 `
  --level flyers `
  --auto-timestamp `
  --output "output_4k.mp4" `
  --resolution 3840x2160 `
  --background white `
  --open-book-gap 24 `
  --render-scale 3 `
  --transition-effect crossfade `
  --transition-duration 0.8 `
  --whisper-model small `
  --language en
```

Goi y model:

- `tiny` hoac `base`: nhanh, do chinh xac thap hon.
- `small`: can bang tot cho Flyers.
- `medium`: cham hon, co the chinh xac hon.

## Batch processing

Batch mode tu match file PDF va audio theo `base filename`.

Vi du:

```text
Flyers 1 Test 1.pdf
Flyers 1 Test 1.mp3
Flyers 1 Test 2.pdf
Flyers 1 Test 2.mp3
```

Se xuat:

```text
outputs/Flyers 1 Test 1.mp4
outputs/Flyers 1 Test 2.mp4
```

Chay batch theo folder:

```powershell
python flyers_video_tool.py `
  --input-dir "C:\input\flyers" `
  --output-dir "C:\output\videos" `
  --batch-report "C:\output\videos\batch_report.csv" `
  --test 1 `
  --auto-timestamp `
  --transition-effect crossfade `
  --transition-duration 0.8 `
  --overwrite
```

Chay batch bang nhieu file roi:

```powershell
python flyers_video_tool.py `
  --pdfs "Flyers 1 Test 1.pdf" "Flyers 1 Test 2.pdf" `
  --audios "Flyers 1 Test 1.mp3" "Flyers 1 Test 2.mp3" `
  --output-dir "outputs" `
  --auto-timestamp `
  --overwrite
```

Trang Test co the duoc infer tu ten file co dang `Test 1`, `Test 2`, `Test 3`. Neu khong co trong filename, tool dung `--test`.

Neu thieu cap PDF hoac audio, tool log warning va bo qua file do. Batch van tiep tuc voi cac cap hop le.

### Manual pairing CSV

Neu ten PDF va audio khong giong nhau, dung `--pairing-csv`. Khi co option nay, tool uu tien CSV va khong auto match theo base filename.

Format `pairing.csv`:

```csv
pdf,audio,output_name,level,test,page_map,ocr_start_page,ocr_end_page,printed_part1_page
Starters Test 1.pdf,Starters Test 1.mp3,Starters Test 1,starters,1,examples/starters_test1_page_map.json,,,
Flyers Test 1.pdf,Flyers Test 1.mp3,Flyers Test 1,flyers,1,,5,12,4
```

Chay:

```powershell
python flyers_video_tool.py `
  --pairing-csv "C:\input\pairing.csv" `
  --output-dir "C:\output\videos" `
  --batch-report "C:\output\videos\batch_report.csv" `
  --auto-timestamp `
  --overwrite
```

Duong dan `pdf` va `audio` trong CSV co the la absolute path, hoac relative path tinh tu thu muc chua `pairing.csv`.
Duong dan `page_map` cung duoc resolve tu thu muc chua `pairing.csv`. Neu mot row khong co `page_map`, tool dung preset theo `level/test` neu co.
Neu row khong co `page_map` nhung co `ocr_start_page` va `ocr_end_page`, batch se auto-detect page map trong pham vi do va xuat `{output_name}_detected_page_map.json`.
CSV chap nhan `printed_start_page` hoac `printed_part1_page`; ca hai deu la trang in cua Part 1 de tinh `pdf_offset`.

Sau batch, tool xuat `batch_report.csv` voi cac cot:

```csv
input_pdf,input_audio,output_video,status,error_message,duration,timestamp_csv
```

Neu mot file failed, report ghi `failed` va batch tiep tuc xu ly file tiep theo.

Trang thai tung file duoc log:

- `matched`
- `processing`
- `timestamp detected`
- `rendering`
- `exported`
- `failed`

`--overwrite` can duoc bat neu output MP4 da ton tai. Neu khong, job do se failed de tranh ghi de nham.

`--csv-only` trong batch chi detect timestamp va xuat CSV/report, khong render MP4.

Transition `crossfade`, `fade`, `slide` duoc tinh tren timeline sao cho tong duration video bang audio goc, sai so muc tieu duoi 0.5 giay. Neu CSV timestamp thu cong lech audio, tool se dieu chinh Part cuoi de khop audio; neu khong the dieu chinh an toan, job se failed va ghi vao report.

## Watermark

Watermark text:

```powershell
python flyers_video_tool.py `
  --pdf "input.pdf" `
  --audio "input.mp3" `
  --test 1 `
  --auto-timestamp `
  --output "output.mp4" `
  --watermark `
  --watermark-text "YLE Listening" `
  --watermark-position bottom-right `
  --watermark-opacity 0.35 `
  --watermark-size 72 `
  --watermark-margin 32
```

Watermark PNG:

```powershell
python flyers_video_tool.py `
  --input-dir "C:\input\flyers" `
  --output-dir "outputs" `
  --auto-timestamp `
  --watermark `
  --watermark-image "logo.png" `
  --watermark-position top-right `
  --watermark-opacity 0.45 `
  --watermark-size 160 `
  --watermark-margin 28
```

Vi tri hop le:

- `top-left`
- `top-right`
- `bottom-left`
- `bottom-right`
- `center`

## Chay Streamlit UI

```powershell
streamlit run app.py
```

Trong UI:

1. Upload PDF.
2. Upload MP3.
3. Chon Test 1/2/3.
4. Bam `Auto detect timestamps`.
5. Sua bang timestamp neu can.
6. Bam `Export video`.
7. Download MP4.

Tab `Batch processing` ho tro:

- Upload nhieu PDF va nhieu audio cung luc.
- Hoac nhap local folder path tren may.
- Upload `pairing.csv` de ghep cap thu cong.
- Chon Level Starters/Movers/Flyers.
- Sua bang page map: Part, PDF pages, Layout.
- Bam `Match files` de xem cap PDF/MP3 duoc match theo base filename.
- Bam `Export batch videos` de tao hang loat MP4.
- Xem status tung file, download tung MP4 da export va download `batch_report.csv`.

## Xu ly loi thuong gap

`FFmpeg was not found in PATH`:

- Cai FFmpeg va mo terminal moi.
- Chay `ffmpeg -version` de kiem tra.

`PDF page X is out of range`:

- PDF scan khong dung file Flyers 1 page map mac dinh, hoac file PDF thieu trang.
- Sua cot `pdf_pages` trong CSV.

`Part X was not detected`:

- Tool van xuat `detected_timestamps.csv`.
- Mo CSV va sua moc thoi gian thu cong, sau do chay lai voi `--timestamps`.

Video lech audio:

- Kiem tra CSV co du 5 Part va Part 5 end bang do dai audio.
- Tool se chan row co `end <= start` va row bi overlap qua muc cho phep.
