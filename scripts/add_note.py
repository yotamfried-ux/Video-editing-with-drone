"""
scripts/add_note.py — Add operator editing notes to a specific draft reel.

Notes are injected into the Gemini analysis prompt the next time the pipeline
re-processes the same footage, giving the AI explicit editorial direction.

Usage:
  python scripts/add_note.py "DRAFT_surfer_Coral_Sallas_20260610.mp4" \
      "Opening clip has no action — pick a more dramatic first moment. Wave outcome clips are cut too early, keep full ride."

  python scripts/add_note.py --list          # show all pending notes
  python scripts/add_note.py --clear "DRAFT_name.mp4"   # remove a note after re-run

After adding notes, re-run the pipeline:
  python scripts/reset_and_rerun.py --reset-only   # restore PROCESSED→RAW
  # Then upload a new file or trigger via GitHub Actions
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.stages.feedback import record_operator_note, clear_operator_note

NOTES_FILE = os.getenv("OPERATOR_NOTES_FILE", "operator_notes.json")


def _list_notes() -> None:
    try:
        with open(NOTES_FILE) as f:
            notes = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print("No operator notes found.")
        return
    if not notes:
        print("No operator notes found.")
        return
    print(f"\n📝 Operator notes ({len(notes)} total):\n")
    for key, entry in notes.items():
        ts   = entry.get("ts", "")[:10]
        note = entry.get("note", "")
        print(f"  [{ts}] {key}")
        print(f"         {note}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Add operator editing notes for a draft reel")
    parser.add_argument("draft", nargs="?", help="Draft filename (e.g. DRAFT_surfer_20260610.mp4)")
    parser.add_argument("note", nargs="?", help="Editing instruction in plain text")
    parser.add_argument("--list", action="store_true", help="List all pending notes")
    parser.add_argument("--clear", metavar="DRAFT", help="Remove a note for a draft")
    args = parser.parse_args()

    if args.list:
        _list_notes()
        return

    if args.clear:
        removed = clear_operator_note(args.clear)
        if removed:
            print(f"✅ Note cleared for '{args.clear}'")
        else:
            print(f"⚠️ No note found for '{args.clear}'")
        return

    if not args.draft or not args.note:
        parser.print_help()
        sys.exit(1)

    record_operator_note(args.draft, args.note)
    print(f"\nℹ️  Note saved. On the next pipeline run, Gemini will receive this instruction.")
    print(f"   To re-process the same footage: python scripts/reset_and_rerun.py --reset-only")


if __name__ == "__main__":
    main()
