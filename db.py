"""Shared MSSQL connection factory for all CobaltaX modules.

Required env vars (set in .env):
  MSSQL_SERVER             hostname or IP, e.g. "sqlserver.cobaltax.local"
  MSSQL_DATABASE           e.g. "cobaltax"
  MSSQL_USER               SQL login
  MSSQL_PASSWORD           SQL password
  MSSQL_TRUSTED_CONNECTION true  → Windows/Kerberos auth (no user/pass needed)

Optional:
  MSSQL_PORT               default 1433
  MSSQL_ENCRYPT            "yes" | "no" | "optional"  (default "yes")
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator

try:
    import pyodbc
except ImportError as _e:
    raise ImportError(
        "pyodbc is required. Run: uv add pyodbc  (or pip install pyodbc)\n"
        "Linux also needs the ODBC driver: "
        "https://learn.microsoft.com/sql/connect/odbc/linux-mac/installing-the-microsoft-odbc-driver-for-sql-server"
    ) from _e

_SERVER   = os.environ.get("MSSQL_SERVER", "localhost")
_PORT     = os.environ.get("MSSQL_PORT", "1433")
_DATABASE = os.environ.get("MSSQL_DATABASE", "cobaltax")
_USER     = os.environ.get("MSSQL_USER", "")
_PASSWORD = os.environ.get("MSSQL_PASSWORD", "")
_TRUSTED  = os.environ.get("MSSQL_TRUSTED_CONNECTION", "false").lower() in ("1", "true", "yes")
_ENCRYPT  = os.environ.get("MSSQL_ENCRYPT", "yes")

_DRIVER_PREF = [
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "ODBC Driver 13 for SQL Server",
]


def _driver() -> str:
    available = [d for d in pyodbc.drivers() if "SQL Server" in d]
    for pref in _DRIVER_PREF:
        if pref in available:
            return pref
    if available:
        return available[0]
    raise RuntimeError(
        "No SQL Server ODBC driver found. "
        "Install 'ODBC Driver 18 for SQL Server' from Microsoft."
    )


def connection_string() -> str:
    drv = _driver()
    base = (
        f"DRIVER={{{drv}}};SERVER={_SERVER},{_PORT};DATABASE={_DATABASE};"
        f"Encrypt={_ENCRYPT};TrustServerCertificate=yes;"
    )
    if _TRUSTED:
        return base + "Trusted_Connection=yes;"
    return base + f"UID={_USER};PWD={_PASSWORD};"


@contextmanager
def get_conn() -> Generator[pyodbc.Connection, None, None]:
    conn = pyodbc.connect(connection_string(), autocommit=False)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
