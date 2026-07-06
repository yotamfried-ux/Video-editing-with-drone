#!/usr/bin/env bash
set +euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_ROOT="${TMP_DIR:-/tmp/dtor}"
DEBUG_DIR="$TMP_ROOT/pipeline-debug"
LOG_FILE="$DEBUG_DIR/run_tracked.log"
SUMMARY_FILE="$DEBUG_DIR/summary.json"
SIDECAR_DIR="$DEBUG_DIR/sidecars"

mkdir -p "$DEBUG_DIR" "$SIDECAR_DIR"
cd "$ROOT_DIR" || exit 98

python scripts/run_tracked.py 2>&1 | tee "$LOG_FILE"
STATUS=${PIPESTATUS[0]}

python - "$DEBUG_DIR" "$TMP_ROOT" "$STATUS" <<'PY'
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

out = Path(sys.argv[1])
tmp = Path(sys.argv[2])
status = int(sys.argv[3])
sidecar_out = out / "sidecars"
sidecar_out.mkdir(parents=True, exist_ok=True)

files = []
sidecars = []
if tmp.exists():
    for path in sorted(tmp.rglob("*")):
        if path.is_file() and "pipeline-debug" not in path.parts:
            rel = str(path.relative_to(tmp))
            size = path.stat().st_size
            files.append({"path": rel, "size_bytes": size})
            if path.name.endswith(".perception.json"):
                sidecars.append(rel)
                target = sidecar_out / path.name
                try:
                    shutil.copy2(path, target)
                except OSError:
                    pass

summary = {
    "exit_code": status,
    "tmp_dir": str(tmp),
    "file_count": len(files),
    "sidecar_count": len(sidecars),
    "sidecars": sidecars,
    "files": files[:500],
}
(out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
PY

exit "$STATUS"
