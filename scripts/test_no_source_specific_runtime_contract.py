#!/usr/bin/env python3
"""MEM-06: no video-specific answer may live in the runtime code or prompts.

Scans every string constant (prompts included) and every comparison operand in pipeline/, integrations/, config/
and services/, EXCEPT docstrings (rationale text may cite the case that motivated a general rule). Fails on:

S1  a GT-v1 source content SHA-256 (full or 12+ hex prefix)
S2  a GT-v1 athlete id (full UUID or its 8-hex prefix)
S3  a DJI source file name / timestamp stem (DJI_YYYYMMDDhhmmss)
S4  a bare GT source index used as a code value (the 24 GT-v1 indices, e.g. "0143")
S5  sanity: the scan finds planted violations in a synthetic module (the guard can fail)

The evaluator side (scripts/, evaluation/) may reference GT; the runtime may not.
"""
from __future__ import annotations

import ast
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ("pipeline", "integrations", "config", "services")
GT_INDICES = {"0070", "0074", "0094", "0095", "0097", "0104", "0108", "0112", "0115", "0118", "0126", "0130", "0131",
              "0140", "0142", "0143", "0146", "0151", "0152", "0155", "0160", "0162", "0163", "0165"}
FAILS: list[str] = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def gt_tokens() -> tuple[set[str], set[str]]:
    gt = json.loads((ROOT / "evaluation" / "ground_truth" / "gtv1_frozen.json").read_text())
    shas = {m["sha256"] for m in gt["members"]}
    athletes = set()
    for m in gt["members"]:
        content = m["content"] if isinstance(m["content"], dict) else json.loads(m["content"])
        athletes |= {s["athlete_id"] for s in content.get("segments", []) if s.get("athlete_id")}
    return shas, athletes


def code_strings(tree: ast.AST) -> list[tuple[int, str]]:
    doc_nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
                doc_nodes.add(id(body[0].value))
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc_nodes]


def violations(files: list[Path], shas: set[str], athletes: set[str]) -> list[str]:
    sha_prefixes = {s[:12] for s in shas}
    ath_prefixes = {a[:8] for a in athletes}
    dji = re.compile(r"DJI_20\d{12}")
    idx = re.compile(r"(?<![\d.])(" + "|".join(sorted(GT_INDICES)) + r")(?![\d.])")
    out = []
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel = path.relative_to(path.parents[len(path.relative_to(ROOT).parts) - 1]) if ROOT in path.parents else path
        for line, text in code_strings(tree):
            low = text.lower()
            hits = [p for p in sha_prefixes if p in low] + [p for p in ath_prefixes if p in low]
            if dji.search(text):
                hits.append("DJI file stem")
            if idx.search(text) and not re.search(r"\d{4}-\d{2}-\d{2}|%|\{", text):
                hits.append("GT source index " + idx.search(text).group(1))
            if hits:
                out.append(f"{rel}:{line}: {hits[:3]} in {text[:60]!r}")
    return out


def main() -> int:
    shas, athletes = gt_tokens()
    files = [p for pkg in RUNTIME for p in (ROOT / pkg).rglob("*.py") if p.is_file()]
    found = violations(files, shas, athletes)
    for v in found[:20]:
        print("   ", v)
    check(not found, f"S1-S4 no GT source hash, athlete id, DJI stem or GT source index in runtime string constants "
                     f"or prompts ({len(files)} files, {len(found)} violations)")
    tmp = Path(tempfile.mkdtemp()) / "planted.py"
    sha, ath = sorted(shas)[0], sorted(athletes)[0]
    tmp.write_text(f'"""doc may cite 0143."""\nX = "{sha[:16]}"\nY = "{ath[:8]}"\nZ = "DJI_20260720164122_0143_D"\n'
                   f'def f(src):\n    """0152 in a docstring is fine."""\n    return src == "0152"\n')
    planted = violations([tmp], shas, athletes)
    check(len(planted) == 4, f"S5 the guard catches planted violations (4 expected, {len(planted)} found) and ignores docstrings")
    print(f"{len(FAILS)} failing")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
