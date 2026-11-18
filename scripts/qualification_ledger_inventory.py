#!/usr/bin/env python3
"""Cycle 12 PA-13: inventory of Review drafts and draft ledgers inside ONE qualification namespace (read-only).

Run inside a qualification run (SPORTREEL_QUALIFICATION_RUN_ID set): every key is mapped into the namespace by
integrations.qualification.NamespacedS3, so production review/ and metadata/ are never read or written here.
  --out FILE    JSON: review objects (key, size, ETag, ledger metadata), ledgers (cid, draft_name, revisions)
  --check       exit 1 unless every review object belongs to exactly one ledgered canonical reel, no canonical reel
                has two review objects, and every ledger's latest revision is committed
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def collect() -> dict:
    from integrations import qualification, r2_storage
    from pipeline import draft_ledger as dl

    if not qualification.active():
        raise SystemExit("refused: not a qualification run")
    store = dl.R2Store()
    review = []
    for obj in r2_storage.list_objects(dl.REVIEW_PREFIX):
        head = store.head(obj["Key"]) or {}
        review.append({"key": obj["Key"], "size": obj.get("Size"), "etag": head.get("etag"),
                       "cid": (head.get("metadata") or {}).get(dl.META_CID),
                       "rev": (head.get("metadata") or {}).get(dl.META_REV)})
    ledgers = []
    for obj in r2_storage.list_objects(dl.LEDGER_PREFIX):
        if "/names/" in obj["Key"] or not obj["Key"].endswith(".json"):
            continue
        entry, _ = store.get_json(obj["Key"])
        if entry:
            ledgers.append({"cid": entry.get("cid"), "draft_name": entry.get("draft_name"),
                            "revisions": entry.get("revisions") or []})
    return {"review": review, "ledgers": ledgers}


def check(inv: dict) -> list[str]:
    problems = []
    names = {l["draft_name"]: l for l in inv["ledgers"]}
    mp4 = [r for r in inv["review"] if r["key"].endswith(".mp4")]
    for r in mp4:
        name = r["key"].split("/", 1)[-1]
        if name not in names:
            problems.append(f"review object without a ledger: {name}")
        elif r.get("cid") and r["cid"] != names[name]["cid"]:
            problems.append(f"review object {name} carries cid {r['cid']} but its ledger is {names[name]['cid']}")
    per_cid = Counter(names[r["key"].split("/", 1)[-1]]["cid"] for r in mp4 if r["key"].split("/", 1)[-1] in names)
    problems += [f"canonical reel {c} has {n} review objects" for c, n in per_cid.items() if n > 1]
    for l in inv["ledgers"]:
        revs = l["revisions"]
        if revs and not revs[-1].get("committed") and any(r["key"].endswith(l["draft_name"]) for r in mp4):
            problems.append(f"ledger {l['cid']}: latest revision not committed")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--input", type=Path, help="evaluate a saved inventory instead of reading R2")
    a = ap.parse_args()
    inv = json.loads(a.input.read_text()) if a.input else collect()
    if a.out:
        a.out.write_text(json.dumps(inv, indent=1))
    problems = check(inv)
    print(json.dumps({"review_objects": len([r for r in inv["review"] if r["key"].endswith(".mp4")]),
                      "ledgers": len(inv["ledgers"]), "problems": problems}, indent=1))
    return 1 if (a.check and problems) else 0


if __name__ == "__main__":
    raise SystemExit(main())
