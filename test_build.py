from flyers_video_tool.flyers_video_tool import ocr_pdf_pages, build_page_map_from_ocr_results
results = ocr_pdf_pages("test/Student's Book - Flyers 1 - 2018.pdf", 'test/ocr', start_page=1, end_page=10)
config, warn = build_page_map_from_ocr_results(results)
print("Config:", config)
print("Warnings:", warn)
