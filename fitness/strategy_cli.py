"""Build the source-covered baseline strategy artifact without model calls."""

import argparse
import json
import os
import tempfile
from pathlib import Path

from .knowledge import build_manifest
from .knowledge_context import build_strategy_library, validate_strategy_coverage


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the baseline fitness strategy library")
    parser.add_argument("--root", type=Path, default=Path("data/knowledge"))
    parser.add_argument("--output", type=Path, default=Path("data/knowledge/baseline-strategies.json"))
    args = parser.parse_args()
    manifest = build_manifest(args.root)
    strategies = build_strategy_library(manifest)
    report = validate_strategy_coverage(manifest, strategies)
    payload = {"version": 1, "coverage": report, "strategies": strategies, "reference_only": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=args.output.parent, suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, args.output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(f"built {len(strategies)} strategies covering {report['covered']} items -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
