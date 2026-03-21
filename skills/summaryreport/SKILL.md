---
name: summaryreport
description: Summarize information from a provided URL that may be an HTML page or PDF, including relevant linked or attached files. Use when the user asks for a report or summary of a source page and its attachments, especially for meeting materials, public notices, policy documents, or multi-file report pages.
---

# URL Attachment Summarizer

## Overview

Produce a single coherent summary from one source URL and its related files.
Detect whether the source is HTML or PDF and then follow the matching procedure file.

## Routing Workflow

1. Confirm the target URL from the user.
2. Detect content type by URL extension, response headers, or initial fetch:
- If source is HTML, follow `references/html-procedure.md`.
- If source is PDF, follow `references/pdf-procedure.md`.
3. If type cannot be determined, ask one focused question or run a lightweight fetch and infer.
4. Execute only the selected procedure file.
5. Merge findings into one final summary with explicit source mapping.

## Recommended Runner

For local execution through Step10 (HTML/PDF auto-detect), use:

`bash scripts/run_summaryreport.sh "<URL>"`

For concurrent or externally tracked runs, prefer fixing the run identifier in the parent process:

`bash scripts/run_summaryreport.sh "<URL>" --run-id "<RUN_ID>"`

For HTML pages that include multiple meetings and need one target only, pass target scope:

`bash scripts/run_summaryreport.sh "<URL>" --target-meeting-name "<会議名>" [--target-round "<回数>"] [--target-date "<yyyymmdd>"] [--target-text "<自由記述>"]`

When the request is specifically to summarize only the prime minister's remarks on an HTML page, use:

`bash scripts/run_summaryreport.sh "<URL>" --summary-focus prime-minister-remarks`

## Execution Control

1. Treat `run_summaryreport.sh` as the single source of truth for one report run. Do not start `step9` or `step10` separately while the parent runner is still in progress.
2. Prefer defining `run_id` in the parent process and passing it via `--run-id`. If auto-generation is used, immediately record the emitted `run_id` and the parent process `PID`. `summaryreport` may run multiple jobs concurrently, so all monitoring and recovery must be tied to that specific `run_id` or remembered `PID`.
3. Determine "still running" from the tracked `run_id`/`PID`, not only from whether output files already exist. Missing `step9-summary.json` or markdown output does not by itself mean the run is stuck.
4. Check status in this order: parent `PID` or tracked run liveness, then parent runner exit status, then artifacts under `tmp/runs/<run_id>/` and `output/`.
5. Do not generalize a failure from a separately invoked step to the original parent run. For example, a DNS or API failure seen in a manual `step9` retry is not proof that the parent `run_summaryreport.sh` failed for the same reason.
6. Only state a root cause when it was observed in the parent run tied to the tracked `run_id`/`PID`. Otherwise, label it as a hypothesis or a failure seen in a separate recovery attempt.
7. Only switch to per-step recovery after confirming that the parent run exited non-zero, or that the tracked `PID` is gone and the expected final artifacts for that same `run_id` were not produced.
8. Before declaring a run abnormal, allow for normal wait time and distinguish clearly between "not finished yet" and "failed".
9. `step6_8_document_pipeline.py` can also take a long time, especially during Step8 LLM summarization when multiple PDFs are processed. When Step6-8 is in progress, wait until the parent run actually exits. If liveness must be judged by elapsed time, do not treat the run as abnormal before 30 minutes have passed since Step6-8 started.
10. `step9_summary_generator.py` can legitimately take a long time. When Step9 is in progress, wait until the parent run actually exits. If liveness must be judged by elapsed time, do not treat the run as abnormal before 30 minutes have passed since Step9 started.
11. Do not stop monitoring only because intermediate artifacts from Step6, Step7, or Step8 already exist, or because Step9/Step10 output has not appeared yet. While Step6-8 or Step9 is running, the correct status is "still running".
12. Do not infer ownership from "the newest directory under `tmp/runs`" or from broad process searches alone. In concurrent runs, those heuristics can point to a different job.

## Procedure Files

1. `references/html-procedure.md`
- Human-defined workflow for HTML start pages.
- Includes how to find and process linked attachments.

2. `references/pdf-procedure.md`
- Human-defined workflow for PDF start files.
- Includes how to find and process related attachments.

3. `references/procedure.md`
- Legacy/shared template.
- Use only when the selected procedure file explicitly references it.

## Attachment Scope Rules

1. Include files directly linked as attachments, appendices, exhibits, agendas, minutes, related materials, or downloads.
2. Exclude unrelated navigation links, ads, account pages, and off-topic pages.
3. Deduplicate repeated links to the same file or content.
4. Prioritize primary documents over mirrored copies.

## Output Requirements

Follow `references/output-format.md`.

At minimum, output:
1. ページの概要。
2. 要約（abstract）。
3. ページの詳細サマリー。

## Quality Checks

Before delivering:
1. Confirm that the correct procedure file was selected from source type.
2. Confirm that all referenced attachments were either processed or explicitly marked unavailable.
3. Confirm that each major claim can be traced to a source.
4. Avoid inventing details not present in the source materials.
5. Keep the summary concise unless the user requests deep detail.
