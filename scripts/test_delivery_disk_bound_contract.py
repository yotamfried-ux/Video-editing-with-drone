#!/usr/bin/env python3
"""Prevent full-quality delivery from accumulating a batch of 4K files on disk."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DELIVERY_PATH = ROOT / "services" / "delivery.py"


def _call_name(node: ast.Call) -> str:
    return node.func.id if isinstance(node.func, ast.Name) else ""


def main() -> int:
    tree = ast.parse(DELIVERY_PATH.read_text(encoding="utf-8"), filename=str(DELIVERY_PATH))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    deliver_final = functions.get("deliver_final")
    if deliver_final is None:
        raise SystemExit("deliver_final is missing")

    assigned_names = {
        target.id
        for node in ast.walk(deliver_final)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    if "downloaded" in assigned_names:
        raise SystemExit("deliver_final must not accumulate a batch-level downloaded mapping")

    per_draft_loops = [
        node
        for node in ast.walk(deliver_final)
        if isinstance(node, ast.For)
        and isinstance(node.target, ast.Name)
        and node.target.id == "draft"
        and isinstance(node.iter, ast.Name)
        and node.iter.id == "to_deliver"
    ]
    if len(per_draft_loops) != 1:
        raise SystemExit("deliver_final must have one per-draft delivery loop")

    loop = per_draft_loops[0]
    try_nodes = [node for node in loop.body if isinstance(node, ast.Try)]
    if len(try_nodes) != 1:
        raise SystemExit("per-draft delivery must use one try/finally boundary")
    boundary = try_nodes[0]

    cleanup_calls = [
        node
        for final_node in boundary.finalbody
        for node in ast.walk(final_node)
        if isinstance(node, ast.Call)
        and _call_name(node) == "_remove"
        and node.args
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "local_path"
    ]
    if not cleanup_calls:
        raise SystemExit("each full-quality local_path must be removed in finally")

    publish_calls = [
        node
        for body_node in boundary.body
        for node in ast.walk(body_node)
        if isinstance(node, ast.Call)
        and _call_name(node) == "_publish_final_reel"
    ]
    if not publish_calls:
        raise SystemExit("each reel must be published while its local file is available")

    print("PASS bounded full-quality delivery disk contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
