# PDF Procedure

Apply this procedure when the provided source URL resolves directly to a PDF file.

## Status

Step 1 is implemented.
Step 2 onward are currently unimplemented and must be skipped.

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
- Step 2 onward: `SKIPPED (unimplemented)`

## Step 1 Implementation

- Script: `scripts/step1_pdf_downloader.py`
- Purpose: download source PDF with fallback browser User-Agent policy.
- Command:
  - `python3 scripts/step1_pdf_downloader.py --url \"<PDF_URL>\" [--run-id \"<RUN_ID>\"]`
- Output artifacts (default):
  - `tmp/runs/<run_id>/step1-pdf.pdf`
  - `tmp/runs/<run_id>/step1-pdf-metadata.json`
