# summaryreport

A repository for generating Japanese summary reports from government HTML/PDF pages and linked materials.

## Current Status

`summaryreport` skill is implemented through Step10 for both HTML and PDF inputs.

## Repository Layout

- `AGENTS.md`: repository and workflow guidelines.
- `skills/summaryreport/SKILL.md`: skill definition.
- `skills/summaryreport/references/`: procedure and output format docs.
- `skills/summaryreport/scripts/`: step scripts (`step0` to `step10`).
- `tmp/runs/<run_id>/`: intermediate artifacts per run.
- `output/`: generated final report files.

## Main Flow (HTML)

1. `step0_init_docling_server.py`
2. `step1_html_content_acquirer.py`
3. `step2_metadata_extractor.py`
4. `step4_minutes_referencer.py`
5. `step5_material_selector.py`
6. `step6_8_document_pipeline.py` (integrated Step6-8)
7. `step9_summary_generator.py`
8. `step10_file_writer.py`

## Main Flow (PDF)

1. `step1_pdf_downloader.py`
2. `step2_metadata_extractor.py --mode pdf` (title from first-page text)
3. `step4_body_digest.py`
4. `step5_material_selector.py`
5. `step6_8_document_pipeline.py` (integrated Step6-8)
6. `step9_summary_generator.py`
7. `step10_file_writer.py`

## One-command Run (HTML/PDF auto-detect)

```bash
bash skills/summaryreport/scripts/run_summaryreport.sh "<URL>"
```

For HTML pages containing multiple meetings, you can scope one target meeting:

```bash
bash skills/summaryreport/scripts/run_summaryreport.sh "<URL>" \
  --target-meeting-name "サイバーセキュリティ推進専門家会議" \
  --target-round "4" \
  --target-date "20260220"
```

## Quick Start

```bash
# 1) optional: ensure docling server is running
python3 skills/summaryreport/scripts/step0_init_docling_server.py

# 2) acquire source
python3 skills/summaryreport/scripts/step1_html_content_acquirer.py \
  --url "https://example.go.jp/page.html" \
  --run-id "20260223T000000Z_example"

# 3) metadata + minutes
python3 skills/summaryreport/scripts/step2_metadata_extractor.py \
  --run-id "20260223T000000Z_example" \
  --mode html \
  --url "https://example.go.jp/page.html"
python3 skills/summaryreport/scripts/step4_minutes_referencer.py \
  --run-id "20260223T000000Z_example"

# 4) materials + integrated pipeline
python3 skills/summaryreport/scripts/step5_material_selector.py \
  --run-id "20260223T000000Z_example"
python3 skills/summaryreport/scripts/step6_8_document_pipeline.py \
  --run-id "20260223T000000Z_example"

# 5) integrated summary + final file
python3 skills/summaryreport/scripts/step9_summary_generator.py \
  --run-id "20260223T000000Z_example"
python3 skills/summaryreport/scripts/step10_file_writer.py \
  --run-id "20260223T000000Z_example"
```

Final output is written to `output/<title>_report.md`.

## Notes

- `OPENAI_API_KEY` is required for Steps 2, 7 (ppt scoring), 8, and 9.
- Abstract section is written in a fenced code block and includes the source URL.

## License

TBD
