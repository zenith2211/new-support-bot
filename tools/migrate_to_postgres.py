"""
tools/migrate_to_postgres.py — copy DATA_DIR's JSON files into Postgres.

    python -m tools.migrate_to_postgres              # show what would move
    python -m tools.migrate_to_postgres --write      # actually move it

Reads the JSON files directly, so it does not care which backend the bot is
configured for. Run it once, with the bot stopped.

Refuses to overwrite a table that already has rows unless you pass --force,
because running this twice against a live database would otherwise roll
balances and stock back to whatever the local files happen to say.
"""

import sys

from app import config, storage
from app.store import TABLE_NAMES


def main(argv: list) -> int:
    write = "--write" in argv
    force = "--force" in argv

    if not config.DATABASE_URL:
        print("DATABASE_URL is not set — nothing to migrate into.")
        print(f"Add it to {config.ENV_FILE_PATH}")
        return 2

    source = storage.JsonBackend()
    try:
        target = storage.PostgresBackend(config.DATABASE_URL)
        target.ensure()
    except Exception as exc:                     # noqa: BLE001
        print(f"cannot reach Postgres: {exc}")
        return 1

    print(f"from  {config.DATA_DIR}")
    print(f"to    postgres ({_host(config.DATABASE_URL)})")
    print(f"mode  {'WRITE' if write else 'dry run'}\n")

    print(f"{'TABLE':<14}{'LOCAL':>8}{'REMOTE':>8}   ACTION")
    print("-" * 48)

    planned = []
    blocked = []
    for name in TABLE_NAMES:
        local = source.load(name)
        remote = target.load(name)
        if not local:
            action = "skip (nothing local)"
        elif remote and not force:
            action = f"BLOCKED — {len(remote)} rows already there"
            blocked.append(name)
        else:
            action = "overwrite" if remote else "copy"
            planned.append((name, local))
        print(f"{name:<14}{len(local):>8}{len(remote):>8}   {action}")

    if blocked:
        print(f"\n{len(blocked)} table(s) already hold data: "
              f"{', '.join(blocked)}")
        print("Pass --force to replace them. That discards whatever is in "
              "Postgres now,\nincluding balances and orders taken since the "
              "last migration.")
        if not force:
            return 1

    if not planned:
        print("\nNothing to do.")
        return 0

    if not write:
        rows = sum(len(data) for _n, data in planned)
        print(f"\nDry run. {rows} records across {len(planned)} tables would "
              f"move.\nRe-run with --write to do it.")
        return 0

    moved = 0
    for name, data in planned:
        target.replace_all(name, data)
        moved += len(data)
        print(f"  moved {len(data):>4} -> {name}")

    print(f"\nDone: {moved} records.")
    print("Verify with:  python -m tools.migrate_to_postgres")
    print("The bot will use Postgres on its next start, because DATABASE_URL "
          "is set.")
    return 0


def _host(dsn: str) -> str:
    """Host only — never print the password."""
    try:
        tail = dsn.split("@", 1)[1]
        return tail.split("/", 1)[0].split("?", 1)[0]
    except (IndexError, AttributeError):
        return "configured"


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
