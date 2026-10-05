#!/usr/bin/env python3
"""Export the immutable pipeline_runs.input_files manifest into GitHub Actions env."""
from __future__ import annotations

import base64
import json
import os
import sys
import urllib.parse
import urllib.request


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].strip():
        raise SystemExit("pipeline run id is required")
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/pipeline_runs?" + urllib.parse.urlencode({
        "id": f"eq.{sys.argv[1].strip()}",
        "select": "input_files",
        "limit": "1",
    })
    request = urllib.request.Request(url, headers={
        "apikey": os.environ["SUPABASE_SERVICE_KEY"],
        "Authorization": "Bearer " + os.environ["SUPABASE_SERVICE_KEY"],
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        rows = json.loads(response.read().decode("utf-8"))
    if len(rows) != 1 or not isinstance(rows[0].get("input_files"), list):
        raise SystemExit("pipeline run has no frozen input manifest")
    manifest = rows[0]["input_files"]
    if not manifest:
        raise SystemExit("pipeline run frozen input manifest is empty")
    compact = json.dumps(manifest, separators=(",", ":"))
    encoded = base64.b64encode(compact.encode()).decode()
    # GitHub env values stay single-line; bootstrap decodes this before storage admission.
    print(f"SPORTREEL_INPUT_MANIFEST_B64={encoded}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
