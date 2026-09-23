#!/usr/bin/env python3
"""Print a compact, secret-free failure summary for a UPL-01 Maestro run.

CI artifacts are not always reachable from the environment that triages a run,
so the decisive facts go into the step log and job summary instead: which
command failed and why (from Maestro's --debug-output commands JSON), and
which texts/ids were on screen (from `maestro hierarchy`).

Usage: summarize_failure.py <evidence-dir> [<step-summary-path>]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Iterator
from xml.etree import ElementTree

MAX_NODES = 60


def _walk(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def failed_commands(evidence: Path) -> list[str]:
    """Describe every command Maestro recorded with status FAILED."""
    lines: list[str] = []
    for path in sorted(evidence.rglob("*.json")):
        if path.name in {"final-maestro-hierarchy.json", "backend-evidence.json"}:
            continue
        try:
            entries = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            lines.append(f"{path.name}: unreadable commands JSON")
            continue
        for entry in entries if isinstance(entries, list) else [entries]:
            metadata = entry.get("metadata") if isinstance(entry, dict) else None
            if not isinstance(metadata, dict) or str(metadata.get("status", "")).upper() != "FAILED":
                continue
            command = entry.get("command", {})
            name = next((key for key, val in command.items() if val is not None), "?") if isinstance(command, dict) else "?"
            detail = command.get(name) if isinstance(command, dict) else None
            error = metadata.get("error")
            message = error.get("message") if isinstance(error, dict) else error
            lines.append(f"{path.name}: FAILED {name} {json.dumps(detail, sort_keys=True)[:300]} -> {str(message)[:500]}")
    return lines


def junit_failures(evidence: Path) -> list[str]:
    """Maestro's own one-line failure reason per flow, from the JUnit report."""
    lines: list[str] = []
    for path in sorted(evidence.glob("*.junit.xml")):
        try:
            root = ElementTree.parse(path).getroot()
        except ElementTree.ParseError:
            continue
        for failure in root.iter("failure"):
            reason = failure.get("message") or (failure.text or "").strip()
            lines.append(f"{path.name}: {reason[:500]}")
    return lines


def log_errors(evidence: Path, limit: int = 12) -> list[str]:
    """Last exception/error lines from each maestro.log."""
    lines: list[str] = []
    for path in sorted(evidence.rglob("maestro.log")):
        hits = [
            line.strip()[:400]
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
            if ("Exception" in line or " ERROR " in line or "[ERROR]" in line or "Assertion" in line)
            # launchApp grants every manifest permission; OEM launcher/badge
            # permissions are unknown on AOSP images and are harmless noise.
            and "Unknown permission" not in line
            and "while executing 'grant'" not in line
        ]
        lines += [f"{path.parent.name}: {hit}" for hit in hits[-limit:]]
    return lines


def visible_nodes(hierarchy_path: Path) -> list[str]:
    """Distinct text / resource-id / accessibility labels on the final screen."""
    if not hierarchy_path.is_file():
        return []
    try:
        tree = json.loads(hierarchy_path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return ["final-maestro-hierarchy.json unreadable"]
    seen: list[str] = []
    for node in _walk(tree):
        attributes = node.get("attributes")
        if not isinstance(attributes, dict):
            continue
        parts = [
            f"{key}={attributes[key]!r}"
            for key in ("text", "resource-id", "accessibilityText", "hintText")
            if attributes.get(key)
        ]
        label = " ".join(parts)
        if label and label not in seen:
            seen.append(label)
        if len(seen) >= MAX_NODES:
            break
    return seen


def main() -> int:
    evidence = Path(sys.argv[1])
    summary_path = Path(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] else None
    failures = junit_failures(evidence) + failed_commands(evidence)
    failures = failures or ["no FAILED command found in Maestro reports"]
    errors = log_errors(evidence)
    nodes = visible_nodes(evidence / "final-maestro-hierarchy.json") or ["(no hierarchy captured)"]
    report = ["### UPL-01 Maestro failure", "", "**Failed command(s)**", ""]
    report += [f"- `{line}`" for line in failures]
    if errors:
        report += ["", "**maestro.log errors**", ""] + [f"- `{line}`" for line in errors]
    report += ["", f"**Final screen (first {MAX_NODES} labelled nodes)**", ""]
    report += [f"- `{line}`" for line in nodes]
    text = "\n".join(report) + "\n"
    print(text)
    if summary_path:
        with summary_path.open("a", encoding="utf-8") as handle:
            handle.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
