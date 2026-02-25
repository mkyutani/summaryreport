#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <URL>" >&2
  exit 1
fi

URL="$1"
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
  python3 skills/pagereport/scripts/step2_metadata_extractor.py --run-id "$RUN_ID" --mode html --url "$URL" --tmp-root "$TMP_ROOT"
  python3 skills/pagereport/scripts/step4_minutes_referencer.py --run-id "$RUN_ID" --tmp-root "$TMP_ROOT"
  python3 skills/pagereport/scripts/step4_body_digest.py --run-id "$RUN_ID" --tmp-root "$TMP_ROOT"
  python3 skills/pagereport/scripts/step5_material_selector.py --run-id "$RUN_ID" --tmp-root "$TMP_ROOT"
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
