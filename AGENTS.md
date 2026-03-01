# Repository Guidelines

## Project Structure & Module Organization
Current implementation centers on the `summaryreport` skill.

- `skills/summaryreport/SKILL.md`: skill entry point and routing.
- `skills/summaryreport/references/`: procedure and output format docs.
- `skills/summaryreport/scripts/`: step-by-step Python scripts (Step0-Step10).
- `tmp/runs/<run_id>/`: per-run intermediate artifacts.
- `output/`: final report markdown files.

If you add new top-level directories, document their purpose here.

## Build, Test, and Development Commands
Primary workflow is script execution from repository root.

- `python3 -m py_compile skills/summaryreport/scripts/<script>.py`: quick syntax check.
- `python3 skills/summaryreport/scripts/step0_init_docling_server.py`: ensure Docling server.
- `python3 skills/summaryreport/scripts/step1_html_content_acquirer.py --url "<URL>" --run-id "<RUN_ID>"`: Step1 for HTML.
- `python3 skills/summaryreport/scripts/step1_pdf_downloader.py --url "<URL>" --run-id "<RUN_ID>"`: Step1 for PDF.
- `python3 skills/summaryreport/scripts/step5_material_selector.py --run-id "<RUN_ID>"`: material selection and download.
- `python3 skills/summaryreport/scripts/step6_8_document_pipeline.py --run-id "<RUN_ID>"`: integrated Step6-8.
- `python3 skills/summaryreport/scripts/step9_summary_generator.py --run-id "<RUN_ID>"`: integrated summary.
- `python3 skills/summaryreport/scripts/step10_file_writer.py --run-id "<RUN_ID>"`: final report writer.
- `bash skills/summaryreport/scripts/run_summaryreport.sh "<URL>"`: auto-detect HTML/PDF and run through Step10.
- `bash skills/summaryreport/scripts/run_summaryreport.sh "<URL>" --target-meeting-name "<会議名>" [--target-round "<回数>"] [--target-date "<yyyymmdd>"]`: HTML multi-meeting scope selection.

## Coding Style & Naming Conventions
Python conventions used in this repository:

- 4-space indentation.
- `snake_case` for modules/functions/variables.
- small, focused scripts per step (`stepN_*.py`).
- UTF-8 text I/O with `errors="replace"` for robustness on government pages.

## Testing Guidelines
No formal test framework is set yet. Use reproducible run-based verification:

- run the target step with a fixed `run_id`.
- inspect `tmp/runs/<run_id>/` outputs.
- validate final report creation in `output/`.

## Commit & Pull Request Guidelines
Use concise imperative commit messages (e.g., `Implement Step9 summary generator`).

- Keep commits scoped by step or concern.
- Document affected scripts and verification command(s) in PR descriptions.
- Avoid bundling unrelated doc and script changes in one commit.

## Agent-Specific Instructions
For this repository, prefer operating through the skill workflow:

1. Follow `skills/summaryreport/references/html-procedure.md` for HTML URLs.
2. Follow `skills/summaryreport/references/pdf-procedure.md` for PDF URLs.
3. Use integrated `step6_8_document_pipeline.py` instead of manually splitting Step6/7/8 unless debugging.
4. Keep final output format aligned with `skills/summaryreport/references/output-format.md`.
