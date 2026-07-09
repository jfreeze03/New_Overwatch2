"""JDBC connection layer for td_sf_compare.

Uses jaydebeapi (JPype under the hood) so the exact same JDBC jars you
already use elsewhere work here. Both jars are loaded into ONE JVM, so
connect_all() must be used rather than starting the JVM twice.
"""

import os

import jaydebeapi
import jpype


def _password(cfg: dict, label: str) -> str:
    env = cfg.get("password_env", "")
    pw = os.environ.get(env, "")
    if not pw:
        raise SystemExit(
            f"[{label}] password env var '{env}' is not set. "
            f"Set it before running (never store passwords in config.yaml)."
        )
    return pw


def connect_all(td_cfg: dict, sf_cfg: dict):
    """Start one JVM with both jars on the classpath, return (td_conn, sf_conn)."""
    jars = [td_cfg["jdbc_jar"], sf_cfg["jdbc_jar"]]
    for j in jars:
        if not os.path.exists(j):
            raise SystemExit(f"JDBC jar not found: {j}")

    if not jpype.isJVMStarted():
        jpype.startJVM(classpath=jars)

    td_conn = jaydebeapi.connect(
        td_cfg["driver_class"],
        td_cfg["url"],
        [td_cfg["user"], _password(td_cfg, "teradata")],
    )
    sf_conn = jaydebeapi.connect(
        sf_cfg["driver_class"],
        sf_cfg["url"],
        [sf_cfg["user"], _password(sf_cfg, "snowflake")],
    )
    return td_conn, sf_conn


def fetch(conn, sql: str) -> list[tuple]:
    """Run a query, return all rows as tuples."""
    cur = conn.cursor()
    try:
        cur.execute(sql)
        return [tuple(r) for r in cur.fetchall()]
    finally:
        cur.close()


def fetch_one(conn, sql: str):
    rows = fetch(conn, sql)
    return rows[0] if rows else None
