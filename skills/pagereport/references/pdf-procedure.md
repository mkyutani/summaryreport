# PDF Procedure

Apply this procedure when the provided source URL resolves directly to a PDF file.

## Status

Step 1 is implemented.
Step 2 is implemented.
Step 4b is implemented (body digest).
Step 5 is implemented.
Step 6-8 integrated pipeline is implemented.
Step 9 is implemented.
Step 10 is implemented.
Step 3 and Step 11 onward are currently unimplemented and must be skipped.

## Arguments

- URL (PDF file, `*.go.jp` domain)

## Fetch Policy (Common for HTML/PDF)

- First try standard HTTP request.
- If blocked or failed (for example 403/406/429), retry with browser-like headers.
- Use this `User-Agent` on retry:
  - `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36`
- Keep this policy for:
  - Step 1 `PDF download`
  - Any related file download in later steps

## Output Spec

Generate one file:
- `output/<タイトル>_report.md`
  - `<タイトル>` is determined in Step 2 (`metadata-extractor`)
  - Include abstract (about 1,000 Japanese characters) inside a code fence
  - Include detailed report after the abstract

## Flow Overview (8 steps)

```text
Step 1: PDF download
Step 2: metadata-extractor -> extract meeting name, date, and iteration number
Step 3: document-type-classifier -> classify document type
Step 4: pdf-converter -> convert PDF
Step 5: material-analyzer -> analyze material
Step 6: summary-generator -> generate abstract
Step 7: file-writer -> output report.md
Step 8: bluesky-poster -> post to Bluesky
```

Current handling:
- Step 1: `IMPLEMENTED`
- Step 2: `IMPLEMENTED`
- Step 3: `SKIPPED (unimplemented)`
- Step 4b: `IMPLEMENTED (body digest)`
- Step 5: `IMPLEMENTED`
- Step 6-8: `IMPLEMENTED (integrated)`
- Step 9: `IMPLEMENTED`
- Step 10: `IMPLEMENTED`
- Step 11 onward: `SKIPPED (unimplemented)`

## Step 1 Implementation

- Script: `scripts/step1_pdf_downloader.py`
- Purpose: download source PDF with fallback browser User-Agent policy.
- Command:
  - `python3 scripts/step1_pdf_downloader.py --url \"<PDF_URL>\" [--run-id \"<RUN_ID>\"]`
- Output artifacts (default):
  - `tmp/runs/<run_id>/source.pdf`
  - `tmp/runs/<run_id>/first-page.txt`
  - `tmp/runs/<run_id>/source.md`
  - `tmp/runs/<run_id>/pdf-links.txt` (empty)
  - `tmp/runs/<run_id>/pdf-links.json` (empty list)
  - `tmp/runs/<run_id>/metadata.json`

## Step 2 Implementation

- Script: `scripts/step2_metadata_extractor.py`
- Purpose:
  - extract title/date/round/page_type with LLM.
  - in `pdf` mode, prioritize `first-page.txt` for title extraction.
- Command:
  - `python3 scripts/step2_metadata_extractor.py --run-id "<RUN_ID>" --mode pdf --url "<PDF_URL>"`
- Output:
  - `tmp/runs/<run_id>/step2-metadata.json`

## Step 4b Implementation (body digest)

- Script: `scripts/step4_body_digest.py`
- Purpose: extract body digest used by Step 9.
- Command:
  - `python3 scripts/step4_body_digest.py --run-id "<RUN_ID>"`
- Output:
  - `tmp/runs/<run_id>/body-digest.json`

## Step 5-10 Implementation

- Step 5: `scripts/step5_material_selector.py`
- Step 6-8 (integrated): `scripts/step6_8_document_pipeline.py`
- Step 9: `scripts/step9_summary_generator.py`
- Step 10: `scripts/step10_file_writer.py`

## End-to-end Command

```bash
bash skills/pagereport/scripts/run_pagereport.sh "<PDF_URL>"
```
