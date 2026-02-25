---
name: pagereport
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

`bash scripts/run_pagereport.sh "<URL>"`

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
