import sqlite3
from typing import Mapping, Any

# --- helpers ---------------------------------------------------------------

def _quote_ident(name: str) -> str:
    # Safe-ish identifier quoting for SQLite
    return '"' + name.replace('"', '""') + '"'

def _infer_sqlite_type(value: Any) -> str:
    # You said only str/int/bool are present. Map to TEXT/INTEGER.
    # (bool is a subclass of int, so this order is fine)
    if isinstance(value, bool):
        return "INTEGER"
    if isinstance(value, int):
        return "INTEGER"
    # default to TEXT for everything else (e.g., str)
    return "TEXT"

def _normalize_value(value: Any) -> Any:
    # Store bools as 0/1
    if isinstance(value, bool):
        return int(value)
    return value

# --- main API --------------------------------------------------------------

def ensure_table_for_row(conn: sqlite3.Connection, table: str, row: Mapping[str, Any]) -> None:
    """
    Create a table on the fly based on the first row's keys and value types.
    Does nothing if the table already exists.
    """
    cols_def = []
    for k, v in row.items():
        col_type = _infer_sqlite_type(v)
        cols_def.append(f"{_quote_ident(k)} {col_type}")
    sql = f"CREATE TABLE IF NOT EXISTS {_quote_ident(table)} (\n  {', '.join(cols_def)}\n)"
    conn.execute(sql)
    conn.commit()

def insert_row(conn: sqlite3.Connection, table: str, row: Mapping[str, Any]) -> None:
    """
    Insert one row (dict of column->value) into the table.
    """
    columns = list(row.keys())
    placeholders = ", ".join(["?"] * len(columns))
    col_sql = ", ".join(_quote_ident(c) for c in columns)
    values = tuple(_normalize_value(row[c]) for c in columns)
    sql = f"INSERT INTO {_quote_ident(table)} ({col_sql}) VALUES ({placeholders})"
    conn.execute(sql, values)
    # caller can batch inside a transaction if they want; committing here is safe but optional
    conn.commit()

# --- example usage ---------------------------------------------------------

if __name__ == "__main__":
    rows = [
        {"id": 1, "name": "alpha", "active": True},
        {"id": 2, "name": "beta",  "active": False},
        {"id": 3, "name": "gamma", "active": True},
    ]

    with sqlite3.connect(":memory:") as conn:
        # first item creates the table; all items get inserted
        for i, r in enumerate(rows):
            if i == 0:
                ensure_table_for_row(conn, "events", r)
            insert_row(conn, "events", r)

        # quick check
        print(conn.execute('SELECT id, name, active FROM "events" ORDER BY id').fetchall())

