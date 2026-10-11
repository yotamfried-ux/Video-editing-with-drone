#!/usr/bin/env python3
"""Combined isolated before/after policy simulation."""
import json
import subprocess
import sys
from pathlib import Path
scripts = ["test_primary_actor_fix_simulation.py", "test_selector_accountability_fix.py",
           "test_manifest_upload_reconciliation_fix.py", "test_business_gate_qa_fix.py"]
results = []
for name in scripts:
    p = subprocess.run([sys.executable, str(Path(__file__).parent / name)],
                       capture_output=True, text=True, check=True)
    results.append({"name": name, "metrics": json.loads(p.stdout)})
assert len(results) == 4
print(json.dumps({"scope": "synthetic isolated combined policy simulation",
                  "production_videos_used": 0, "test_groups_passed": 4,
                  "historical_failure_counts_remeasured": False,
                  "results": results}, indent=2))
