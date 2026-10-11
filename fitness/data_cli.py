"""Explicit local data operations: python -m fitness.data_cli --help."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from .data_transfer import (
    confirm_feedback_import,
    create_backup,
    preview_feedback_import,
    preview_restore,
    restore_backup,
)
from .storage import Conflict, Store


def main(argv=None):
    for output in (sys.stdout, sys.stderr):
        if hasattr(output, "reconfigure"):
            output.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Local fitness data preview, confirmation, backup and restore")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("import-preview", "import-confirm"):
        sub = commands.add_parser(name)
        sub.add_argument("--source", type=Path, required=True)
        sub.add_argument("--format", choices=["json", "csv", "markdown"])
        if name == "import-confirm":
            sub.add_argument("--database", type=Path, required=True)
            sub.add_argument("--batch-id", required=True)
            sub.add_argument("--confirm", action="store_true")
    sub = commands.add_parser("backup")
    sub.add_argument("--database", type=Path, required=True)
    sub.add_argument("--destination", type=Path, required=True)
    sub = commands.add_parser("restore-preview")
    sub.add_argument("--source", type=Path, required=True)
    sub.add_argument("--database", type=Path, required=True)
    sub = commands.add_parser("restore-confirm")
    sub.add_argument("--source", type=Path, required=True)
    sub.add_argument("--database", type=Path, required=True)
    sub.add_argument("--source-fingerprint", required=True)
    sub.add_argument("--target-fingerprint")
    sub.add_argument("--confirm", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command.startswith("import-"):
            content = args.source.read_text(encoding="utf-8-sig")
            format = args.format or {".json": "json", ".csv": "csv", ".md": "markdown"}.get(args.source.suffix)
            if args.command == "import-preview":
                result = preview_feedback_import(content, format)
            else:
                if not args.confirm:
                    raise ValueError("导入前需要 --confirm 明确确认。")
                result = confirm_feedback_import(Store(args.database), content, format, args.batch_id,
                                                 confirmed=args.confirm)
        elif args.command == "backup":
            if not args.database.is_file():
                raise FileNotFoundError(args.database)
            result = create_backup(Store(args.database), args.destination)
        elif args.command == "restore-preview":
            result = preview_restore(args.source, args.database)
        else:
            result = restore_backup(args.source, args.database, args.source_fingerprint,
                                    expected_target_fingerprint=args.target_fingerprint, confirmed=args.confirm)
    except (ValueError, OSError, Conflict, sqlite3.Error) as exc:
        parser.exit(2, f"{exc}\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
