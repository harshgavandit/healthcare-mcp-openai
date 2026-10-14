"""
Tool 2B: query_patient_database
----------------------------------
Accepts a SQL SELECT query and executes it against patients.db.

Safety guardrail: Only SELECT statements are allowed.
Any INSERT, UPDATE, DELETE, DROP, etc. will be rejected.

Run independently to test:
    python tools/query_tool.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from db import get_connection
import sqlite3
from contextlib import closing


def query_patient_database(sql_query: str, max_rows: int = 50) -> dict:
    """
    Executes a read-only SQL query and returns the results.

    Args:
        sql_query: A SQL SELECT statement to run.
        max_rows:  Maximum number of rows to return (default 50).

    Returns:
        A dict with: results, sql, row_count, status, and error (if any).
    """
    if isinstance(max_rows, bool) or not isinstance(max_rows, int) or not 1 <= max_rows <= 500:
        return {"status": "error", "error": "max_rows must be an integer between 1 and 500.",
                "sql": sql_query, "results": [], "row_count": 0}
    # --- Safety check: only allow SELECT statements ---
    # Strip leading whitespace and check the first keyword
    cleaned = sql_query.strip().upper()
    if not cleaned.startswith("SELECT"):
        return {
            "status":    "error",
            "error":     "Only SELECT statements are allowed. Write operations are not permitted.",
            "sql":       sql_query,
            "results":   [],
            "row_count": 0,
        }

    # --- Execute the query ---
    try:
        with closing(get_connection(read_only=True)) as conn:
            # Deny SQL side effects, including functions invoked inside SELECT.
            allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
            def authorize(action, arg1, arg2, database, trigger):
                if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() == "load_extension":
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY
            conn.set_authorizer(authorize)
            # Bound expensive recursive/cross-join queries.
            steps = 0
            def progress():
                nonlocal steps
                steps += 1
                return int(steps > 1000)
            conn.set_progress_handler(progress, 1000)
            cursor = conn.execute(sql_query)
            results = [dict(row) for row in cursor.fetchmany(max_rows)]
        row_count = len(results)

        return {
            "status":    "success",
            "sql":       sql_query,
            "row_count": row_count,
            "results":   results,
        }

    except Exception as e:
        return {
            "status":    "error",
            "error":     str(e),
            "sql":       sql_query,
            "results":   [],
            "row_count": 0,
        }


# ---------- Quick test (This section is only for testing the tool separately)----------
if __name__ == "__main__":
    import json

    # Test 1: valid SELECT
    q1 = "SELECT name, age, gender FROM patients ORDER BY age DESC"
    print("=== Test 1: Valid SELECT ===")
    print(json.dumps(query_patient_database(q1), indent=2))

    # Test 2: rejected write operation
    q2 = "DELETE FROM patients WHERE patient_id = 1"
    print("\n=== Test 2: Rejected DELETE ===")
    print(json.dumps(query_patient_database(q2), indent=2))

    # Test 3: join query
    q3 = """
        SELECT p.name, d.diagnosis_name, d.diagnosis_type
        FROM patients p
        JOIN diagnoses d ON p.patient_id = d.patient_id
        WHERE d.diagnosis_type = 'chronic'
        LIMIT 10
    """
    print("\n=== Test 3: JOIN query ===")
    print(json.dumps(query_patient_database(q3), indent=2))
