# Repository Guidelines

## Project Structure & Module Organization
Current implementation centers on the `pagereport` skill.

- `skills/pagereport/SKILL.md`: skill entry point and routing.
- `skills/pagereport/references/`: procedure and output format docs.
- `skills/pagereport/scripts/`: step-by-step Python scripts (Step0-Step10).
- `tmp/runs/<run_id>/`: per-run intermediate artifacts.
- `output/`: final report markdown files.

If you add new top-level directories, document their purpose here.

## Build, Test, and Development Commands
Primary workflow is script execution from repository root.

- `python3 -m py_compile skills/pagereport/scripts/<script>.py`: quick syntax check.
- `python3 skills/pagereport/scripts/step0_init_docling_server.py`: ensure Docling server.
- `python3 skills/pagereport/scripts/step1_html_content_acquirer.py --url "<URL>" --run-id "<RUN_ID>"`: Step1 for HTML.
- `python3 skills/pagereport/scripts/step5_material_selector.py --run-id "<RUN_ID>"`: material selection and download.
- `python3 skills/pagereport/scripts/step6_8_document_pipeline.py --run-id "<RUN_ID>"`: integrated Step6-8.
- `python3 skills/pagereport/scripts/step9_summary_generator.py --run-id "<RUN_ID>"`: integrated summary.
- `python3 skills/pagereport/scripts/step10_file_writer.py --run-id "<RUN_ID>"`: final report writer.

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

1. Follow `skills/pagereport/references/html-procedure.md` for HTML URLs.
2. Use integrated `step6_8_document_pipeline.py` instead of manually splitting Step6/7/8 unless debugging.
3. Keep final output format aligned with `skills/pagereport/references/output-format.md`.
