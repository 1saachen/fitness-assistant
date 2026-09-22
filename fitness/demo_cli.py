"""Command line entry points for reproducible local demos."""

import argparse
import json
import sys
from pathlib import Path

from .config import Settings
from .demo import DemoDataError, initialize_demo_profile, reset_runtime_data
from .storage import Store


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="循序 Fitness Assistant 本地演示数据工具")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="在空数据库中初始化演示档案")
    init.add_argument("--db-path", type=Path, help="覆盖默认 SQLite 路径")
    init.add_argument("--profile-path", type=Path, help="覆盖默认演示档案路径")

    reset = subparsers.add_parser("reset", help="删除本地 SQLite 演示运行数据")
    reset.add_argument("--confirm", action="store_true", help="确认删除本地运行数据")
    reset.add_argument("--db-path", type=Path, help="覆盖默认 SQLite 路径")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    db_path = args.db_path or settings.db_path

    try:
        if args.command == "init":
            profile_path = args.profile_path or settings.example_path
            result = initialize_demo_profile(Store(db_path), profile_path)
        else:
            if not args.confirm:
                print("重置本地数据需要显式传入 --confirm。", file=sys.stderr)
                return 2
            result = reset_runtime_data(db_path)
    except DemoDataError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
