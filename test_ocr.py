from flyers_video_tool.flyers_video_tool import ocr_pdf_pages
results = ocr_pdf_pages(
    pdf_path="test/Student's Book - Flyers 1 - 2018.pdf",
    output_dir="test/ocr",
    start_page=1,
    end_page=10
)
for r in results:
    print(f"--- Page {r['page']} ---")
    print(r['text'][:500])
