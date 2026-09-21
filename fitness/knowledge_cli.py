"""Build a reviewable, source-enriched manifest for the maintained knowledge."""

import argparse
import json
from pathlib import Path

from .knowledge import build_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the approved fitness knowledge manifest")
    parser.add_argument("--root", type=Path, default=Path("data/knowledge"))
    parser.add_argument("--output", type=Path, default=Path("data/knowledge/manifest.json"))
    args = parser.parse_args()
    manifest = build_manifest(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"indexed {len(manifest)} approved knowledge items -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
