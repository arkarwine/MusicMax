#!/usr/bin/env python3
"""Manage bot sudo users directly in SQLite.

This script intentionally avoids importing the bot package so it can be used
when the bot is stopped, broken, or missing optional runtime dependencies.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path


DEFAULT_DB_PATH = "data/anonxmusic.db"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _strip_env_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _load_dotenv_value(key: str) -> str | None:
    env_path = _repo_root() / ".env"
    if not env_path.exists():
        return None

    for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        env_key, env_value = line.split("=", 1)
        if env_key.strip() == key:
            return _strip_env_quotes(env_value)
    return None


def _database_path(explicit_path: str | None) -> Path:
    configured = explicit_path or os.getenv("DATABASE_PATH") or _load_dotenv_value("DATABASE_PATH")
    path = Path(configured or DEFAULT_DB_PATH).expanduser()
    if not path.is_absolute():
        path = _repo_root() / path
    return path


def _parse_user_ids(values: list[str]) -> list[int]:
    user_ids: list[int] = []
    for value in values:
        for item in value.replace(",", " ").split():
            try:
                user_id = int(item)
            except ValueError:
                raise SystemExit(f"Invalid Telegram user ID: {item}") from None
            if user_id <= 0:
                raise SystemExit(f"Invalid Telegram user ID: {item}")
            user_ids.append(user_id)
    return user_ids


def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sudoers (
            user_id INTEGER PRIMARY KEY
        )
        """
    )
    return conn


def add_sudo(db_path: Path, user_ids: list[int]) -> None:
    with _connect(db_path) as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO sudoers (user_id) VALUES (?)",
            [(user_id,) for user_id in user_ids],
        )
    print(f"Added sudo user(s): {', '.join(map(str, user_ids))}")
    print("Restart the bot for this to affect the running process.")


def remove_sudo(db_path: Path, user_ids: list[int]) -> None:
    with _connect(db_path) as conn:
        conn.executemany("DELETE FROM sudoers WHERE user_id = ?", [(user_id,) for user_id in user_ids])
    print(f"Removed sudo user(s): {', '.join(map(str, user_ids))}")
    print("Restart the bot for this to affect the running process.")


def list_sudo(db_path: Path) -> None:
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT user_id FROM sudoers ORDER BY user_id").fetchall()

    if not rows:
        print("No sudo users found.")
        return

    print("Sudo users:")
    for index, (user_id,) in enumerate(rows, start=1):
        print(f"{index}. {user_id}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage bot sudo users in SQLite.")
    parser.add_argument(
        "--db",
        help=f"SQLite database path. Defaults to DATABASE_PATH from env/.env, then {DEFAULT_DB_PATH}.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Add one or more sudo users.")
    add_parser.add_argument("user_ids", nargs="+", help="Telegram user IDs. Commas are also accepted.")

    remove_parser = subparsers.add_parser("remove", aliases=["rm", "delete", "del"], help="Remove sudo users.")
    remove_parser.add_argument("user_ids", nargs="+", help="Telegram user IDs. Commas are also accepted.")

    subparsers.add_parser("list", aliases=["ls"], help="List sudo users.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    db_path = _database_path(args.db)

    if args.command == "add":
        add_sudo(db_path, _parse_user_ids(args.user_ids))
    elif args.command in {"remove", "rm", "delete", "del"}:
        remove_sudo(db_path, _parse_user_ids(args.user_ids))
    elif args.command in {"list", "ls"}:
        list_sudo(db_path)
    else:
        parser.error(f"Unknown command: {args.command}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
