# HTML Procedure

Apply this procedure when the provided source URL resolves to an HTML page.

## Status

Step 0 is implemented.
Step 1 is implemented (Docling server required).
Step 1 substeps (clean/title/pdf-links) are implemented as helper scripts.
Step 1.5 is implemented (optional target meeting selector for multi-meeting pages).
Step 2 is implemented for core metadata (meeting name, date, round).
Step 4 is implemented (minutes source selection).
Step 5 is implemented (material scoring and selection).
Step 6 is implemented (parallel document pipeline + deferred resolution).
Step 7 is implemented (type-based conversion).
Step 8 is implemented (LLM per-document summarization for Step9 input).
Step 9 is implemented (integrated summary generation).
Step 10 is implemented (final markdown writer).
Step 11 onward are currently unimplemented and must be skipped.

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
- Step 1.5: `IMPLEMENTED (optional target meeting selector)`
- Step 2: `IMPLEMENTED (meeting name/date/round only)`
- Step 3: `OPTIONAL (skip by default)`
- Step 4: `IMPLEMENTED (html/pdf/none branching)`
- Step 5: `IMPLEMENTED (scoring + selection)`
- Step 6: `IMPLEMENTED (parallel classify + early analysis + deferred resolve)`
- Step 7: `IMPLEMENTED (ppt important-page markdown, word/other full text)`
- Step 8: `IMPLEMENTED (LLM per-document summarization)`
- Step 9: `IMPLEMENTED (meeting/report branched integrated summary)`
- Step 10: `IMPLEMENTED (output/<title>_report.md writer)`
- Step 11 onward: `SKIPPED (unimplemented)`

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
  - `tmp/runs/<run_id>/pdf-links.json` (structured links with estimated category)
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
  - Model default is `gpt-5-mini` (override with `PAGEREPORT_STEP2_MODEL`).
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

## Step 1.5 Implementation (optional, HTML only)

- Script: `scripts/step1_5_meeting_selector.py`
- Purpose:
  - when one HTML page includes multiple meetings, select one target scope and prepare scoped inputs.
- Command:
  - `python3 scripts/step1_5_meeting_selector.py --run-id "<RUN_ID>" --target-meeting-name "<会議名>" [--target-round "<回数>"] [--target-date "<yyyymmdd>"] [--target-text "<自由記述>"]`
- Outputs:
  - `tmp/runs/<run_id>/selected-source.md`
  - `tmp/runs/<run_id>/selected-pdf-links.json`
  - `tmp/runs/<run_id>/selected-pdf-links.txt`
  - `tmp/runs/<run_id>/selection-metadata.json`
- Downstream:
  - when Step 1.5 is applied, Step2/Step4/Step5 should use selected files.

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

## Step 5 Implementation

- Script: `scripts/step5_material_selector.py`
- Purpose:
  - score each PDF link and select materials needed for summarization.
- Command:
  - `python3 scripts/step5_material_selector.py --run-id "<RUN_ID>"`
- Inputs (default):
  - `tmp/runs/<run_id>/pdf-links.json` (preferred)
  - `tmp/runs/<run_id>/pdf-links.txt` (fallback)
  - `tmp/runs/<run_id>/minutes.md` (optional bonus source)
- Output:
  - `tmp/runs/<run_id>/step5-material-selection.json`
  - `tmp/runs/<run_id>/step5-selected-*.pdf` (selected PDFs downloaded in run root; no subdirectory)
- Document categories:
  - `agenda`, `minutes`, `executive_summary`, `material`, `reference`,
    `participants`, `seating`, `disclosure_method`, `personal_material`, `other`
- Selection rule:
  - select PDFs with `priority_score >= 4`
  - if selected count exceeds 5, keep top 5 by score
  - exception: if a summary/full pair is detected, include both and mark as pending decision
- Deferred decision fields (for Step 6 resolution):
  - `deferred_decisions[]` with rule `prefer_full_if_pages_le_20_else_summary`
  - `selected_pdfs[].decision_pending = true`
  - `selected_pdfs[].decision_group_id` and `decision_role` (`summary` / `full`)

## Step 6 Implementation

Preferred execution mode for Step6-8:
- Script: `scripts/step6_8_document_pipeline.py`
- Command:
  - `python3 scripts/step6_8_document_pipeline.py --run-id "<RUN_ID>"`
- Behavior:
  - resolve deferred selection once.
  - for each final-selected PDF, run `Step6 -> Step7 -> Step8` continuously in the same worker.
  - run workers in parallel across PDFs.
  - still writes standard output files for compatibility:
    - `tmp/runs/<run_id>/step6-document-pipeline.json`
    - `tmp/runs/<run_id>/step7-conversion.json`
    - `tmp/runs/<run_id>/step8-material-summaries.json`

Legacy split mode (still available):
- Script: `scripts/step6_document_pipeline.py`
- Purpose:
  - process selected PDFs in parallel.
  - classify document type (Word-like / PowerPoint-like / agenda / participants / press / survey).
  - resolve `deferred_decisions` using page count rule.
- Command:
  - `python3 scripts/step6_document_pipeline.py --run-id "<RUN_ID>"`
- Inputs:
  - `tmp/runs/<run_id>/step5-material-selection.json`
- Internal processing:
  - Phase A (lightweight): `pdfinfo` for page count on Step5-selected PDFs, then resolve deferred pairs.
  - Phase B (full): run `pdftotext -f 1 -l 5` and document-type classification only on `final_selected_pdfs`.
  - parallel per PDF where applicable (thread pool).
- Deferred resolution rule:
  - if full document pages `<= 20`: choose full.
  - else: choose summary.
- Output:
  - `tmp/runs/<run_id>/step6-document-pipeline.json`
    - `per_pdf_analysis`
    - `resolved_deferred_decisions`
    - `final_selected_pdfs`

## Step 7 Implementation

When using preferred integrated mode, Step 7 runs inside:
- `scripts/step6_8_document_pipeline.py`

Legacy standalone mode:
- Script: `scripts/step7_conversion_pipeline.py`
- Purpose:
  - convert `final_selected_pdfs` using Step6 document type.
- Command:
  - `python3 scripts/step7_conversion_pipeline.py --run-id "<RUN_ID>"`
- Inputs:
  - `tmp/runs/<run_id>/step6-document-pipeline.json`
- Processing:
  - all docs: `pdftotext` full-text conversion.
  - `powerpoint_like`: detect important pages from slide title lines and emit markdown excerpt.
  - `word_like` / `mixed` / `other`: use `pdftotext` full text as-is.
  - per-PDF parallel execution where possible.
- Output:
  - `tmp/runs/<run_id>/step7-conversion.json`
- `tmp/runs/<run_id>/step7-*.txt`
- `tmp/runs/<run_id>/step7-*.md` (for powerpoint-like docs only)

## Step 8 Implementation

When using preferred integrated mode, Step 8 runs inside:
- `scripts/step6_8_document_pipeline.py`

Legacy standalone mode:
- Script: `scripts/step8_material_summarizer.py`
- Purpose:
  - summarize each Step7-converted material with LLM for Step9 integration input.
- Command:
  - `python3 scripts/step8_material_summarizer.py --run-id "<RUN_ID>"`
- Inputs:
  - `tmp/runs/<run_id>/step7-conversion.json`
- Processing:
  - `powerpoint_like + markdown`:
    - strategy `ppt_selected_pages_md` (summarize selected pages markdown from Step7).
  - text outputs (`word_like` / `mixed` / `other`):
    - adaptive read strategies by line count:
      - `word_small` (full text)
      - `word_medium` (head/tail + keyword windows)
      - `word_large` / `word_xlarge` (compressed windows)
  - per-document parallel processing with configurable workers.
  - empty-content detection delegated to LLM output schema.
- LLM requirements:
  - `OPENAI_API_KEY` must be set.
  - model default: `gpt-5-mini` (override with `PAGEREPORT_STEP8_MODEL`).
  - optional endpoint override: `OPENAI_API_BASE`.
- Output:
  - `tmp/runs/<run_id>/step8-material-summaries.json`
    - `per_document[].summary`
    - `per_document[].key_points`
    - `per_document[].read_strategy`
    - `per_document[].used_sections`
    - `per_document[].empty_content`, `empty_reason`

## Step 9 Implementation

- Script: `scripts/step9_summary_generator.py`
- Purpose:
  - generate overall integrated summary from:
    - Step2 meeting/report metadata
    - Step4 minutes (when available)
    - Step8 per-document summaries
- Command:
  - `python3 scripts/step9_summary_generator.py --run-id "<RUN_ID>"`
- Inputs:
  - `tmp/runs/<run_id>/step2-metadata.json`
  - `tmp/runs/<run_id>/minutes-source.json`
  - `tmp/runs/<run_id>/minutes-extraction.json`
  - `tmp/runs/<run_id>/minutes.md` (optional)
  - `tmp/runs/<run_id>/step8-material-summaries.json`
- Processing:
  - branch by `page_type` from Step2:
    - `MEETING`: include meeting context and minutes-aware wording.
    - `REPORT`: focus on report/policy content (no fake meeting-discussion phrasing).
  - generate:
    - `abstract_ja` (<= 1500 chars, retry once if too long)
    - `overall_summary_ja`
  - if `MEETING` and no minutes available, explicitly note that verbatim discussion details are unavailable.
- LLM requirements:
  - `OPENAI_API_KEY` must be set.
  - model default: `gpt-5-mini` (override with `PAGEREPORT_STEP9_MODEL`).
- Output:
  - `tmp/runs/<run_id>/step9-summary.json`
    - `abstract_ja`
    - `overall_summary_ja`
    - `minutes_used`, `minutes_note`
    - `materials_coverage`

## Step 10 Implementation

- Script: `scripts/step10_file_writer.py`
- Purpose:
  - write final report markdown file from Step2/Step9 (and Step8 details).
- Command:
  - `python3 scripts/step10_file_writer.py --run-id "<RUN_ID>"`
- Inputs:
  - `tmp/runs/<run_id>/step2-metadata.json`
  - `tmp/runs/<run_id>/step9-summary.json`
  - `tmp/runs/<run_id>/step8-material-summaries.json` (optional)
- Output:
  - `output/<タイトル>_report.md` (from Step2 `output_report_path`)
  - `tmp/runs/<run_id>/step10-output.json` (validation metadata)
- Required formatting:
  - report has 3 major sections:
    - `ページの概要`
    - `要約（Abstract）`
    - `ページの詳細サマリー`
  - `要約（Abstract）` must be in a fenced code block.
  - source URL must be included inside the abstract code block (for Bluesky usage).

## Execution Order

- Default order:
  - `Step 0 -> Step 1 -> Step 2 -> Step 4 -> Step 5 -> (Step6-8 integrated per PDF) -> Step 9 -> Step 10 -> ...`
- Equivalent split order (legacy):
  - `Step 0 -> Step 1 -> Step 2 -> Step 4 -> Step 5 -> Step 6 -> Step 7 -> Step 8 -> Step 9 -> Step 10 -> ...`
- `Step 3` is optional and should run only when additional overview quality is needed.
