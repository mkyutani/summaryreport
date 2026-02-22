# HTML Procedure

Apply this procedure when the provided source URL resolves to an HTML page.

## Status

Step 0 is implemented.
Step 1 is implemented (Docling server required).
Step 1 substeps (clean/title/pdf-links) are implemented as helper scripts.
Other steps are currently unimplemented and must be skipped.

## Arguments

- URL (HTML page, `*.go.jp` domain)

## Fetch Policy (Common for HTML/PDF)

- First try standard HTTP request.
- If blocked or failed (for example 403/406/429), retry with browser-like headers.
- Use this `User-Agent` on retry:
  - `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36`
- Keep this policy for:
  - Step 1 `content-acquirer` (HTML retrieval)
  - Any linked file download in Step 5 `material-selector`

## Output Spec

Generate one file:
- `output/<タイトル>_report.md`
  - `<タイトル>` is determined in Step 2 (`metadata-extractor`)
  - Include abstract (about 1,000 Japanese characters) inside a code fence
  - Include detailed report after the abstract

## Flow Overview (Step 0 + 11 steps)

```text
Step 0: docling-init -> ensure docling server is running
Step 1: content-acquirer -> HTML retrieval and PDF link extraction
Step 2: metadata-extractor -> extract meeting name, date, and iteration number
Step 2.5: page-type-detector -> detect page type
Step 3: overview-creator -> create meeting overview
Step 4: minutes-referencer -> reference minutes
Step 5: material-selector -> select and download materials
Step 6: document-type-classifier (parallel) -> classify document type
Step 7: pdf-converter (parallel) -> convert PDF
Step 8: material-analyzer (parallel) -> analyze materials
Step 9: summary-generator -> generate abstract
Step 10: file-writer -> output report.md
Step 11: bluesky-poster -> post to Bluesky
```

Current handling:
- Step 0: `IMPLEMENTED`
- Step 1: `IMPLEMENTED`
- Step 1 substeps (clean/title/pdf-links): `IMPLEMENTED (helper scripts)`
- Other steps: `SKIPPED (unimplemented)`

## Step 0 Implementation

- Script: `scripts/step0_init_docling_server.py`
- Purpose: start `docling-server`; if missing, pull image and run container.
- Command:
  - `python3 scripts/step0_init_docling_server.py`

## Step 1 Implementation

- Script: `scripts/step1_html_content_acquirer.py`
- Purpose: fetch HTML and extract candidate PDF links. Also convert source via Docling server.
- Command:
  - `python3 scripts/step1_html_content_acquirer.py --url \"<HTML_URL>\" [--run-id \"<RUN_ID>\"]`
- Docling mode:
  - Endpoint default: `http://127.0.0.1:5001/v1/convert/source`
  - Docling is always used in Step 1. If conversion fails, Step 1 fails.
- Output artifacts (default):
  - `tmp/runs/<run_id>/step1-html.html`
  - `tmp/runs/<run_id>/step1-pdf-links.txt`
  - `tmp/runs/<run_id>/step1-html-metadata.json`
  - `tmp/runs/<run_id>/step1-docling.md` (when Docling succeeds)
  - `tmp/runs/<run_id>/step1-docling-response.json` (when Docling succeeds)

## Step 1 Substep Implementations

- Step 1 substep: HTML cleaning:
  - Script: `scripts/step1_html_cleaner.py`
  - Command: `python3 scripts/step1_html_cleaner.py --html-file "<HTML_FILE>" --run-id "<RUN_ID>"`
  - Output:
    - `tmp/runs/<run_id>/step1/clean/cleaned.html`
    - `tmp/runs/<run_id>/step1/clean/cleaned-outline.md`
    - `tmp/runs/<run_id>/step1/clean/cleaned-metadata.json`

- Step 1 substep: page title extraction:
  - Script: `scripts/step1_page_title_extractor.py`
  - Command: `python3 scripts/step1_page_title_extractor.py --html-file "<HTML_FILE>" --run-id "<RUN_ID>"`
  - Output:
    - `tmp/runs/<run_id>/step1/title/page-title.json`

- Step 1 substep: PDF link extraction and absolute URL conversion:
  - Script: `scripts/step1_pdf_link_extractor.py`
  - Command: `python3 scripts/step1_pdf_link_extractor.py --base-url "<BASE_URL>" --html-file "<HTML_FILE>" --run-id "<RUN_ID>"`
  - Output:
    - `tmp/runs/<run_id>/step1/pdf-links/pdf-links.json`
    - `tmp/runs/<run_id>/step1/pdf-links/pdf-links-metadata.json`
