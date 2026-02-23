# summaryreport

A repository for generating Japanese summary reports from government HTML/PDF pages and linked materials.

## Current Status

`pagereport` skill is implemented through Step10.

## Repository Layout

- `AGENTS.md`: repository and workflow guidelines.
- `skills/pagereport/SKILL.md`: skill definition.
- `skills/pagereport/references/`: procedure and output format docs.
- `skills/pagereport/scripts/`: step scripts (`step0` to `step10`).
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

## Quick Start

```bash
# 1) optional: ensure docling server is running
python3 skills/pagereport/scripts/step0_init_docling_server.py

# 2) acquire source
python3 skills/pagereport/scripts/step1_html_content_acquirer.py \
  --url "https://example.go.jp/page.html" \
  --run-id "20260223T000000Z_example"

# 3) metadata + minutes
python3 skills/pagereport/scripts/step2_metadata_extractor.py \
  --run-id "20260223T000000Z_example" \
  --mode html \
  --url "https://example.go.jp/page.html"
python3 skills/pagereport/scripts/step4_minutes_referencer.py \
  --run-id "20260223T000000Z_example"

# 4) materials + integrated pipeline
python3 skills/pagereport/scripts/step5_material_selector.py \
  --run-id "20260223T000000Z_example"
python3 skills/pagereport/scripts/step6_8_document_pipeline.py \
  --run-id "20260223T000000Z_example"

# 5) integrated summary + final file
python3 skills/pagereport/scripts/step9_summary_generator.py \
  --run-id "20260223T000000Z_example"
python3 skills/pagereport/scripts/step10_file_writer.py \
  --run-id "20260223T000000Z_example"
```

Final output is written to `output/<title>_report.md`.

## Notes

- `OPENAI_API_KEY` is required for Steps 2, 7 (ppt scoring), 8, and 9.
- Abstract section is written in a fenced code block and includes the source URL.

## License

TBD
