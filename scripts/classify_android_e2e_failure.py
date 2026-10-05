#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re
from pathlib import Path

INFRA = {
    "device_offline": re.compile(r"device offline|DeviceServerDiedException|gRPC.*UNAVAILABLE", re.I),
    "disk_exhaustion": re.compile(r"No space left on device|ENOSPC", re.I),
    "binder_failure": re.compile(r"FAILED BINDER TRANSACTION|TransactionTooLargeException", re.I),
    "emulator_boot": re.compile(r"emulator.*(?:failed|timeout)|AVD.*(?:failed|timeout)", re.I),
}

def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--log", required=True)
    p.add_argument("--output", required=True)
    a=p.parse_args()
    text=Path(a.log).read_text(encoding="utf-8", errors="replace") if Path(a.log).exists() else ""
    matches=[name for name,rx in INFRA.items() if rx.search(text)]
    result={"classification":"infrastructure" if matches else "product_or_test","retryable":bool(matches),"signals":matches}
    Path(a.output).write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(result))
    return 0 if matches else 1
if __name__=="__main__": raise SystemExit(main())
