# HTML Procedure

Apply this procedure when the provided source URL resolves to an HTML page.

## Status

Step 0 is implemented.
Step 1 is implemented (Docling server required).
Step 1 substeps (clean/title/pdf-links) are implemented as helper scripts.
Step 2 is implemented for core metadata (meeting name, date, round).
Step 4 is implemented (minutes source selection).
Step 5 onward are currently unimplemented and must be skipped.

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
Step 2: metadata-extractor -> detect page type and extract meeting name/date/round
Step 3: overview-creator -> optional (skip by default)
Step 4: minutes-referencer -> reference minutes (default: run after Step 2)
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
- Step 2: `IMPLEMENTED (meeting name/date/round only)`
- Step 3: `OPTIONAL (skip by default)`
- Step 4: `IMPLEMENTED (html/pdf/none branching)`
- Step 5 onward: `SKIPPED (unimplemented)`

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
  - `tmp/runs/<run_id>/source.html`
  - `tmp/runs/<run_id>/source.md` (Docling markdown cleaned for downstream parsing)
    - Includes frontmatter: `source_title`, `source_og_title`
  - `tmp/runs/<run_id>/pdf-links.txt`
  - `tmp/runs/<run_id>/metadata.json`
  - `tmp/runs/<run_id>/docling-response.json` (debug/trace)

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

## Step 2 Implementation

- Script: `scripts/step2_metadata_extractor.py`
- Purpose: pass full `source.md` to LLM, detect page type, and extract metadata directly.
- Command:
  - `python3 scripts/step2_metadata_extractor.py --run-id "<RUN_ID>" --mode html --url "<HTML_URL>" --md-file "tmp/runs/<run_id>/source.md"`
- Output:
  - `tmp/runs/<run_id>/step2-metadata.json`
- LLM requirements:
  - `OPENAI_API_KEY` must be set.
  - Model default is `gpt-4.1-mini` (override with `PAGEREPORT_STEP2_MODEL`).
- Extracted fields:
  - `page_type`
  - `meeting_name`
  - `date` (`yyyymmdd`)
  - `round` (`round_number`, `round_text`)
  - `reasoning_brief`
  - `report_title`
  - `output_report_path`
- Date post-validation:
  - Validate LLM date against date candidates extracted from `source.md`.
  - If LLM date is not in candidates, fallback to the first date candidate in `source.md`.

## Step 4 Specification (minutes-referencer)

- Inputs:
  - `tmp/runs/<run_id>/source.md`
  - `tmp/runs/<run_id>/pdf-links.txt`
- Goal:
  - Find a minutes source for downstream summarization.
  - Preferred output is one selected source (HTML section or minutes PDF).

### Branching Rules

1. HTML本文に議事録/議事要旨がある場合
- Detect in `source.md` by heading/keyword match such as:
  - `議事録`, `議事要旨`, `議事概要`, `会議概要`
- Output selection:
  - `minutes_source.type = "html"`
  - `minutes_source.path = "tmp/runs/<run_id>/source.md"`
  - `minutes_source.anchor = <matched heading text>`

2. HTML本文に十分な議事録情報がなく、議事録PDFがある場合
- Detect from `pdf-links.txt` by filename/link text keywords such as:
  - `gijiroku`, `gijiyoshi`, `minutes`, `議事録`, `議事要旨`
- Output selection:
  - `minutes_source.type = "pdf"`
  - `minutes_source.url = <selected PDF URL>`
  - `minutes_source.reason = "filename/text keyword match"`

3. どちらにもない場合
- Output selection:
  - `minutes_source.type = "none"`
  - `minutes_source.reason = "no minutes content in html and no minutes-like pdf link"`
- This is not fatal. Continue to Step 5.

### Expected Output File

- `tmp/runs/<run_id>/minutes-source.json`
  - Contains selected source and branch decision.
  - Downstream steps use this file as first reference for minutes context.

## Step 4 Implementation

- Script: `scripts/step4_minutes_referencer.py`
- Command:
  - `python3 scripts/step4_minutes_referencer.py --run-id "<RUN_ID>"`
- Inputs (default):
  - `tmp/runs/<run_id>/source.md`
  - `tmp/runs/<run_id>/pdf-links.txt`
- Output:
  - `tmp/runs/<run_id>/minutes-source.json`

## Execution Order

- Default order:
  - `Step 0 -> Step 1 -> Step 2 -> Step 4 -> Step 5 -> ...`
- `Step 3` is optional and should run only when additional overview quality is needed.
