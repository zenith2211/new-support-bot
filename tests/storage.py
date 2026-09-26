"""
tests/storage.py — both storage backends, including the lost-update property.

    python -m tests.storage                  # JSON backend only
    DATABASE_URL=postgres://... python -m tests.storage

The Postgres checks are skipped without DATABASE_URL, and the exit code stays
0 — but the concurrency check is the whole reason this file exists, so run it
against a real database before trusting a serverless deploy.

Uses a throwaway table prefix and deletes it afterwards, so it is safe to
point at the same database the bot uses.
"""

import os
import sys
import threading

os.environ.setdefault("BOT_TOKEN", "123456:test-token-not-real")
os.environ.setdefault("ADMIN_IDS", "1")

FAILURES: list = []


def check(name: str, got, want):
    if got != want:
        FAILURES.append(f"{name}: got {got!r}, want {want!r}")


def ok(name: str, condition: bool, detail: str = ""):
    if not condition:
        FAILURES.append(f"{name}{': ' + detail if detail else ''}")


def exercise(backend, label: str):
    """Every backend must behave identically for the basics."""
    table = "t_probe"
    backend.ensure()

    # Start clean. A run killed part-way through leaves rows behind, and
    # without this the next run fails on residue rather than on a real bug.
    backend.replace_all(table, {})
    check(f"{label}: empty table", backend.load(table), {})

    backend.put(table, "u1", {"balance": 5}, {"u1": {"balance": 5}})
    check(f"{label}: put then load", backend.load(table),
          {"u1": {"balance": 5}})

    # `stock` values are lists, not dicts — the schema must not assume objects.
    whole = {"u1": {"balance": 5}, "p1": ["line-a", "line-b"]}
    backend.put(table, "p1", ["line-a", "line-b"], whole)
    check(f"{label}: list record survives", backend.load(table).get("p1"),
          ["line-a", "line-b"])

    # mutate returning None must change nothing.
    def refuse(_record):
        return None

    backend.mutate(table, "u1", refuse, whole)
    check(f"{label}: refused mutate is a no-op",
          backend.load(table).get("u1"), {"balance": 5})

    def bump(record):
        record = dict(record or {})
        record["balance"] = record.get("balance", 0) + 10
        return record

    backend.mutate(table, "u1", bump, whole)
    check(f"{label}: mutate writes", backend.load(table).get("u1"),
          {"balance": 15})

    backend.delete(table, "p1", {"u1": {"balance": 15}})
    ok(f"{label}: delete removes the row",
       "p1" not in backend.load(table), str(backend.load(table)))

    backend.replace_all(table, {})
    check(f"{label}: replace_all clears", backend.load(table), {})


def concurrency(backend, label: str):
    """The property that matters: N concurrent credits must all land.

    A plain get/save loses updates here — each thread reads the same balance
    and writes back its own total, so the final figure is one increment, not
    N. mutate() takes a row lock, so every increment survives.
    """
    table = "t_probe_conc"
    threads = 8
    per_thread = 5
    backend.replace_all(table, {"w": {"balance": 0}})

    def add_one(record):
        record = dict(record or {})
        record["balance"] = float(record.get("balance") or 0) + 1
        return record

    def worker():
        for _ in range(per_thread):
            backend.mutate(table, "w", add_one, {})

    pool = [threading.Thread(target=worker) for _ in range(threads)]
    for thread in pool:
        thread.start()
    for thread in pool:
        thread.join()

    expected = threads * per_thread
    final = (backend.load(table).get("w") or {}).get("balance")
    check(f"{label}: no credits lost under {threads} threads", final,
          float(expected))
    backend.replace_all(table, {})


def conversation_state_survives_a_process():
    """The admin panel is prompt-driven: tap "Add stock", then send the lines
    as a separate message. On serverless those two arrive at two different
    processes, so a prompt held in module memory is gone by the time the
    reply lands and the action silently does nothing.

    Simulated by dropping the table caches between the two steps, which is
    what a fresh invocation gets.
    """
    from app import config, state, store

    user = 4242424242
    state.clear_prompt(user)

    # Invocation A: admin taps "Add stock".
    state.set_prompt(user, "ad_stock_add", pid="pspot1")

    # Invocation B: a genuinely separate process. Reloading a table cache
    # here would prove nothing — it would not have cleared the module-level
    # dict the old implementation used, so the old code would pass too.
    import json as _json
    import subprocess
    import sys as _sys

    probe = (
        "from app import state;"
        f"r = state.get_prompt({user});"
        "import json;"
        "print('PROBE' + json.dumps(r))"
    )
    env = dict(os.environ)
    env["DATA_DIR"] = config.DATA_DIR
    env["PYTHONIOENCODING"] = "utf-8"
    out = subprocess.run([_sys.executable, "-c", probe], capture_output=True,
                         text=True, env=env, timeout=120).stdout
    line = next((l for l in out.splitlines() if l.startswith("PROBE")), "")
    record = _json.loads(line[5:]) if line else None

    ok("prompt survives a separate process", record is not None,
       "the admin form would silently do nothing on serverless")
    if record:
        check("prompt keeps its mode", record.get("mode"), "ad_stock_add")
        check("prompt keeps its data", (record.get("data") or {}).get("pid"),
              "pspot1")

    state.clear_prompt(user)
    store.prompts.reload()
    ok("clear_prompt really clears", state.get_prompt(user) is None)

    # Same for a picked coupon, which is read on a later message too.
    state.set_coupon(user, "pspot1", "SAVE10")
    state.set_coupon(user, "pgemin1", "HALF")
    store.coupon_picks.reload()
    check("coupon survives a new process",
          state.get_coupon(user, "pspot1"), "SAVE10")
    check("a second product keeps its own coupon",
          state.get_coupon(user, "pgemin1"), "HALF")

    state.clear_coupon(user, "pspot1")
    store.coupon_picks.reload()
    check("clearing one coupon leaves the other",
          state.get_coupon(user, "pgemin1"), "HALF")
    check("cleared coupon is gone", state.get_coupon(user, "pspot1"), "")
    state.clear_coupon(user, "pgemin1")


def warm_container_sees_other_writers():
    """store.reload_all() must drop every table cache.

    Table._cache never expires. In one long-lived process that is fine —
    it owns its data. On Vercel a warm container is reused, so a container
    that cached force_join=False kept answering False after an admin turned
    it on from another container: the write reached Postgres and the writing
    container, and nothing else. api/telegram.py calls reload_all() per
    invocation; this pins that it actually clears things.
    """
    from app import store

    store.settings.put("t_probe_setting", {"value": "first"})
    check("setting reads back", store.setting("t_probe_setting"), "first")

    # Another container writes straight to the backend, behind this
    # process's cache — exactly what a second Lambda does.
    whole = dict(store.settings.all())
    whole["t_probe_setting"] = {"value": "second"}
    store.backend.put("settings", "t_probe_setting", {"value": "second"},
                      whole)

    ok("a stale cache is genuinely stale",
       store.setting("t_probe_setting") == "first",
       "the cache did not hold, so this test proves nothing")

    store.reload_all()

    # Every table, not just the one that happened to be read.
    still_cached = [t.name for t in store.all_tables()
                    if t._cache is not None]
    ok("reload_all clears every table", not still_cached,
       f"still cached: {still_cached}")

    check("reload_all picks up the other writer",
          store.setting("t_probe_setting"), "second")

    store.settings.delete("t_probe_setting")


def destructive_suites_are_isolated():
    """smoke and flow buy, credit, ban and delete. Both must pin themselves to
    the JSON backend, because their DATA_DIR guard is meaningless once
    DATABASE_URL is set — store.py would quietly use Postgres instead."""
    import pathlib
    import re

    for name in ("smoke", "flow"):
        source = pathlib.Path(__file__).with_name(f"{name}.py").read_text(
            encoding="utf-8")
        head = source.split("from app import", 1)[0]
        for var in ("DATABASE_URL", "POSTGRES_URL"):
            pinned = re.search(
                rf'os\.environ\["{var}"\]\s*=\s*""', head)
            ok(f"tests/{name}.py pins {var} before importing app",
               bool(pinned),
               "a live database would be used for a destructive suite")


def table_registry():
    """store.TABLE_NAMES drives the migration tool. If a new Table is added
    and not listed, that table silently fails to migrate — so pin it."""
    from app import store
    declared = set(store.TABLE_NAMES)
    actual = {value.name for value in vars(store).values()
              if isinstance(value, store.Table)}
    ok("TABLE_NAMES lists every table", declared == actual,
       f"missing {actual - declared or '-'}, extra {declared - actual or '-'}")


def main() -> int:
    import tempfile
    from app import config

    # ── JSON backend ──────────────────────────────────────────
    config.DATA_DIR = tempfile.mkdtemp(prefix="storage-json-")
    from app import storage
    json_backend = storage.JsonBackend()
    exercise(json_backend, "json")
    concurrency(json_backend, "json")
    table_registry()
    conversation_state_survives_a_process()
    warm_container_sees_other_writers()
    destructive_suites_are_isolated()
    print("  [     ok] json backend" if not FAILURES
          else f"  [FAIL x{len(FAILURES)}] json backend")

    # ── Postgres backend ──────────────────────────────────────
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not dsn:
        print("  [   skip] postgres backend (set DATABASE_URL to run)")
        print()
        print("The concurrency check on Postgres is the one that validates a")
        print("serverless deploy. Run it before trusting one.")
    else:
        before = len(FAILURES)
        try:
            pg = storage.PostgresBackend(dsn)
            exercise(pg, "postgres")
            concurrency(pg, "postgres")
        except Exception as exc:                 # noqa: BLE001
            import traceback
            traceback.print_exc()
            FAILURES.append(f"postgres: raised {type(exc).__name__}: {exc}")
        broke = len(FAILURES) - before
        print(f"  [{('FAIL x' + str(broke)) if broke else 'ok':>7}] "
              f"postgres backend")

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}):")
        for problem in FAILURES:
            print(f"  - {problem}")
        return 1
    print("storage checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
