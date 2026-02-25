#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 <URL> [--target-meeting-name <name>] [--target-round <round>] [--target-date <yyyymmdd>] [--target-text <text>]" >&2
  exit 1
fi

URL="$1"
shift

TARGET_MEETING_NAME=""
TARGET_ROUND=""
TARGET_DATE=""
TARGET_TEXT=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --target-meeting-name)
      TARGET_MEETING_NAME="${2:-}"
      shift 2
      ;;
    --target-round)
      TARGET_ROUND="${2:-}"
      shift 2
      ;;
    --target-date)
      TARGET_DATE="${2:-}"
      shift 2
      ;;
    --target-text)
      TARGET_TEXT="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done
TMP_ROOT="${TMP_ROOT:-tmp/runs}"

RUN_ID="$(python3 - <<'PY'
from datetime import datetime, timezone
from uuid import uuid4
print(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:6])
PY
)"

detect_mode() {
  local url="$1"
  if [[ "$url" =~ \.pdf([?#].*)?$ ]]; then
    echo "pdf"
    return
  fi
  python3 - "$url" <<'PY'
import sys
from urllib import request, error

url = sys.argv[1]

def detect(u: str) -> str:
    # Try HEAD first, then GET headers.
    for method in ("HEAD", "GET"):
        try:
            req = request.Request(u, method=method)
            with request.urlopen(req, timeout=20) as resp:
                ctype = (resp.headers.get("Content-Type") or "").lower()
                if "application/pdf" in ctype:
                    return "pdf"
                if "text/html" in ctype:
                    return "html"
        except Exception:
            continue
    # conservative fallback
    if u.lower().endswith(".pdf"):
        return "pdf"
    return "html"

print(detect(url))
PY
}

MODE="$(detect_mode "$URL")"

echo "run_id=$RUN_ID mode=$MODE"

if [ "$MODE" = "html" ]; then
  python3 skills/pagereport/scripts/step0_init_docling_server.py
  python3 skills/pagereport/scripts/step1_html_content_acquirer.py --url "$URL" --run-id "$RUN_ID" --tmp-root "$TMP_ROOT"
  SOURCE_MD_PATH="$TMP_ROOT/$RUN_ID/source.md"
  PDF_LINKS_JSON_PATH="$TMP_ROOT/$RUN_ID/pdf-links.json"
  PDF_LINKS_TXT_PATH="$TMP_ROOT/$RUN_ID/pdf-links.txt"

  if [ -n "$TARGET_MEETING_NAME" ] || [ -n "$TARGET_ROUND" ] || [ -n "$TARGET_DATE" ] || [ -n "$TARGET_TEXT" ]; then
    python3 skills/pagereport/scripts/step1_5_meeting_selector.py \
      --run-id "$RUN_ID" \
      --tmp-root "$TMP_ROOT" \
      --target-meeting-name "$TARGET_MEETING_NAME" \
      --target-round "$TARGET_ROUND" \
      --target-date "$TARGET_DATE" \
      --target-text "$TARGET_TEXT"
    SOURCE_MD_PATH="$TMP_ROOT/$RUN_ID/selected-source.md"
    PDF_LINKS_JSON_PATH="$TMP_ROOT/$RUN_ID/selected-pdf-links.json"
    PDF_LINKS_TXT_PATH="$TMP_ROOT/$RUN_ID/selected-pdf-links.txt"
  fi

  python3 skills/pagereport/scripts/step2_metadata_extractor.py --run-id "$RUN_ID" --mode html --url "$URL" --tmp-root "$TMP_ROOT" --md-file "$SOURCE_MD_PATH" --pdf-links-file "$PDF_LINKS_TXT_PATH"
  python3 skills/pagereport/scripts/step4_minutes_referencer.py --run-id "$RUN_ID" --tmp-root "$TMP_ROOT" --md-file "$SOURCE_MD_PATH" --pdf-links-file "$PDF_LINKS_TXT_PATH"
  python3 skills/pagereport/scripts/step4_body_digest.py --run-id "$RUN_ID" --tmp-root "$TMP_ROOT" --source-md-file "$SOURCE_MD_PATH"
  python3 skills/pagereport/scripts/step5_material_selector.py --run-id "$RUN_ID" --tmp-root "$TMP_ROOT" --pdf-links-file "$PDF_LINKS_TXT_PATH" --pdf-links-json-file "$PDF_LINKS_JSON_PATH"
  python3 skills/pagereport/scripts/step6_8_document_pipeline.py --run-id "$RUN_ID" --tmp-root "$TMP_ROOT"
  python3 skills/pagereport/scripts/step9_summary_generator.py --run-id "$RUN_ID" --tmp-root "$TMP_ROOT"
  python3 skills/pagereport/scripts/step10_file_writer.py --run-id "$RUN_ID" --tmp-root "$TMP_ROOT"
else
  python3 skills/pagereport/scripts/step1_pdf_downloader.py --url "$URL" --run-id "$RUN_ID" --tmp-root "$TMP_ROOT"
  python3 skills/pagereport/scripts/step2_metadata_extractor.py --run-id "$RUN_ID" --mode pdf --url "$URL" --tmp-root "$TMP_ROOT"
  python3 skills/pagereport/scripts/step4_body_digest.py --run-id "$RUN_ID" --tmp-root "$TMP_ROOT"
  python3 skills/pagereport/scripts/step5_material_selector.py --run-id "$RUN_ID" --tmp-root "$TMP_ROOT"
  python3 skills/pagereport/scripts/step6_8_document_pipeline.py --run-id "$RUN_ID" --tmp-root "$TMP_ROOT"
  python3 skills/pagereport/scripts/step9_summary_generator.py --run-id "$RUN_ID" --tmp-root "$TMP_ROOT"
  python3 skills/pagereport/scripts/step10_file_writer.py --run-id "$RUN_ID" --tmp-root "$TMP_ROOT"
fi

echo "done run_id=$RUN_ID"
