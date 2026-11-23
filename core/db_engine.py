"""
Database Engine & Sandboxing Module
Provides schema management, mock data seeding, query execution, dry-run simulation,
and dynamic schema/database ingestion (.sql DDL & .db binary files).
"""

import io
import os
import sqlite3
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional, Tuple


SAMPLE_SCHEMA_DDL = """
-- Customers Table
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    country TEXT NOT NULL,
    loyalty_points INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Departments Table
CREATE TABLE IF NOT EXISTS departments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    budget REAL NOT NULL,
    manager_id INTEGER
);

-- Employees Table
CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    department_id INTEGER NOT NULL,
    salary REAL NOT NULL,
    hire_date DATE NOT NULL,
    FOREIGN KEY (department_id) REFERENCES departments(id)
);

-- Orders Table
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    order_date DATE NOT NULL,
    total_amount REAL NOT NULL,
    status TEXT CHECK(status IN ('pending', 'processing', 'shipped', 'delivered', 'cancelled')) NOT NULL,
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);

-- Order Items Table
CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    product_name TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    unit_price REAL NOT NULL CHECK(unit_price >= 0),
    FOREIGN KEY (order_id) REFERENCES orders(id)
);
"""

SAMPLE_DATA_SEED = """
-- Insert Customers
INSERT INTO customers (name, email, country, loyalty_points, created_at) VALUES
('Alice Johnson', 'alice.j@example.com', 'USA', 450, '2023-01-15 08:30:00'),
('Bob Smith', 'bob.smith@example.com', 'UK', 120, '2023-03-22 14:15:00'),
('Carlos Mendez', 'carlos.m@example.com', 'Spain', 890, '2022-11-05 11:45:00'),
('Diana Prince', 'diana.p@example.com', 'USA', 310, '2023-05-18 16:20:00'),
('Evan Wright', 'evan.w@example.com', 'Canada', 50, '2023-08-01 09:10:00'),
('Fatima Al-Hassan', 'fatima.h@example.com', 'UAE', 720, '2023-02-14 13:00:00');

-- Insert Departments
INSERT INTO departments (name, budget, manager_id) VALUES
('Engineering', 250000.0, 1),
('Sales & Marketing', 180000.0, 3),
('Finance', 120000.0, 5),
('Customer Support', 95000.0, 7);

-- Insert Employees
INSERT INTO employees (name, department_id, salary, hire_date) VALUES
('Gregory House', 1, 115000.0, '2021-04-01'),
('James Wilson', 1, 92000.0, '2022-06-15'),
('Lisa Cuddy', 2, 105000.0, '2020-02-10'),
('Eric Foreman', 2, 78000.0, '2023-01-20'),
('Robert Chase', 3, 85000.0, '2022-09-01'),
('Allison Cameron', 3, 82000.0, '2023-03-11'),
('Chris Taub', 4, 62000.0, '2023-07-01'),
('Remy Hadley', 4, 65000.0, '2023-08-15');

-- Insert Orders
INSERT INTO orders (customer_id, order_date, total_amount, status) VALUES
(1, '2023-09-01', 349.50, 'delivered'),
(1, '2023-10-12', 120.00, 'shipped'),
(2, '2023-09-14', 89.99, 'delivered'),
(3, '2023-08-20', 1450.00, 'delivered'),
(3, '2023-10-02', 290.00, 'processing'),
(4, '2023-09-28', 540.25, 'delivered'),
(4, '2023-10-15', 75.00, 'pending'),
(5, '2023-10-10', 45.00, 'delivered'),
(6, '2023-07-19', 980.00, 'delivered'),
(6, '2023-09-25', 410.50, 'shipped');

-- Insert Order Items
INSERT INTO order_items (order_id, product_name, quantity, unit_price) VALUES
(1, 'Wireless Noise-Canceling Headphones', 1, 249.50),
(1, 'USB-C Fast Charging Cable (2m)', 2, 50.00),
(2, 'Mechanical Gaming Keyboard', 1, 120.00),
(3, 'Smart Ergonomic Office Chair', 1, 89.99),
(4, 'Ultra-Wide 34-inch 4K Monitor', 2, 600.00),
(4, 'Heavy-Duty Monitor Desk Arm', 1, 250.00),
(5, 'Noise-Isolating Earbuds', 2, 145.00),
(6, 'Standing Desk Converter 36-inch', 1, 450.00),
(6, 'Anti-Fatigue Comfort Floor Mat', 1, 90.25),
(7, 'Bluetooth Multi-Device Mouse', 1, 75.00),
(8, 'Laptop Aluminum Stand', 1, 45.00),
(9, 'Smart Home Air Purifier HEPA', 2, 400.00),
(9, 'Replacement HEPA Carbon Filters', 3, 60.00),
(10, 'Portable SSD 2TB Rugged', 1, 280.50),
(10, 'High-Speed USB-C Hub 7-in-1', 1, 130.00);
"""


class DatabaseEngine:
    """Manages an embedded SQLite database sandbox with dynamic schema loading and isolation."""

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self.is_custom_schema = False
        self.custom_schema_source = "default"
        # For :memory:, use shared uri or hold persistent connection
        if db_path == ":memory:":
            self._shared_conn = sqlite3.connect(
                "file:sql_sandbox?mode=memory&cache=shared", uri=True, check_same_thread=False
            )
            self._shared_conn.row_factory = sqlite3.Row
            self._shared_conn.execute("PRAGMA foreign_keys = ON;")
        else:
            self._shared_conn = None
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        if self._shared_conn is not None:
            return self._shared_conn
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def close(self) -> None:
        """Closes any persistent shared connection."""
        with self._lock:
            if self._shared_conn is not None:
                try:
                    self._shared_conn.close()
                except Exception:
                    pass
                self._shared_conn = None

    def __del__(self) -> None:
        self.close()

    def _init_database(self) -> None:
        """Initializes tables and seeds default dataset."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.executescript(SAMPLE_SCHEMA_DDL)
            
            cursor.execute("SELECT COUNT(*) FROM customers;")
            count = cursor.fetchone()[0]
            if count == 0:
                cursor.executescript(SAMPLE_DATA_SEED)
            conn.commit()
            if self._shared_conn is None:
                conn.close()

    def _drop_all_user_tables(self, conn: sqlite3.Connection) -> None:
        """Drops all non-system SQLite tables and views."""
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = OFF;")
        # Drop views
        cursor.execute("SELECT name FROM sqlite_master WHERE type='view';")
        for row in cursor.fetchall():
            cursor.execute(f'DROP VIEW IF EXISTS "{row[0]}";')
        # Drop tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
        for row in cursor.fetchall():
            cursor.execute(f'DROP TABLE IF EXISTS "{row[0]}";')
        cursor.execute("PRAGMA foreign_keys = ON;")
        conn.commit()

    def reset_database(self) -> Dict[str, Any]:
        """Wipes sandbox and restores pristine default schema and seed data."""
        with self._lock:
            conn = self._get_connection()
            self._drop_all_user_tables(conn)
            cursor = conn.cursor()
            cursor.executescript(SAMPLE_SCHEMA_DDL)
            cursor.executescript(SAMPLE_DATA_SEED)
            conn.commit()
            self.is_custom_schema = False
            self.custom_schema_source = "default"
            if self._shared_conn is None:
                conn.close()
        return {
            "success": True,
            "message": "Database reset to default enterprise e-commerce schema.",
            "schema_context": self.get_schema_context()
        }

    def load_custom_ddl(self, ddl_sql: str) -> Dict[str, Any]:
        """
        Loads custom user/jury DDL and optional seed INSERTs into the sandbox.
        Replaces current tables with the uploaded schema definition.
        """
        if not ddl_sql or not ddl_sql.strip():
            return {"success": False, "error": "Provided DDL script is empty."}

        with self._lock:
            conn = self._get_connection()
            try:
                self._drop_all_user_tables(conn)
                cursor = conn.cursor()
                cursor.executescript(ddl_sql)
                conn.commit()
                self.is_custom_schema = True
                self.custom_schema_source = "custom_ddl"
                if self._shared_conn is None:
                    conn.close()
            except Exception as e:
                # If loading fails, restore default schema to avoid corrupted state
                try:
                    self._drop_all_user_tables(conn)
                    conn.cursor().executescript(SAMPLE_SCHEMA_DDL)
                    conn.cursor().executescript(SAMPLE_DATA_SEED)
                    conn.commit()
                    self.is_custom_schema = False
                    self.custom_schema_source = "default"
                except Exception:
                    pass
                return {
                    "success": False,
                    "error": f"Failed to apply DDL script: {str(e)}",
                    "schema_context": self.get_schema_context()
                }

        context = self.get_schema_context()
        table_count = len(context)
        return {
            "success": True,
            "message": f"Successfully loaded custom schema with {table_count} table(s).",
            "table_count": table_count,
            "schema_context": context
        }

    def load_custom_db_bytes(self, db_bytes: bytes, filename: str = "custom.db") -> Dict[str, Any]:
        """
        Loads an uploaded SQLite database file into the sandboxed connection.
        Clones database in-memory using sqlite3 backup API.
        """
        if not db_bytes:
            return {"success": False, "error": "Uploaded database file is empty."}

        with self._lock:
            temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".sqlite")
            try:
                temp_db.write(db_bytes)
                temp_db.flush()
                temp_db.close()

                # Open temp db and verify it is a valid SQLite file
                source_conn = sqlite3.connect(temp_db.name)
                source_cursor = source_conn.cursor()
                source_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
                tables = [r[0] for r in source_cursor.fetchall()]

                target_conn = self._get_connection()
                self._drop_all_user_tables(target_conn)

                # Use SQLite online backup API to copy from temp disk DB to in-memory sandbox
                source_conn.backup(target_conn)
                source_conn.close()

                self.is_custom_schema = True
                self.custom_schema_source = f"file:{filename}"
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Invalid SQLite database file: {str(e)}"
                }
            finally:
                if os.path.exists(temp_db.name):
                    try:
                        os.unlink(temp_db.name)
                    except Exception:
                        pass

        context = self.get_schema_context()
        return {
            "success": True,
            "message": f"Successfully loaded SQLite database '{filename}' with {len(context)} table(s).",
            "table_count": len(context),
            "schema_context": context
        }

    def get_schema_ddl(self) -> str:
        """Returns active DDL definitions from sqlite_master."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT sql FROM sqlite_master WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL ORDER BY type DESC, name;"
                )
                ddls = [row[0] + ";" for row in cursor.fetchall() if row[0]]
                if ddls:
                    return "\n\n".join(ddls)
                return SAMPLE_SCHEMA_DDL.strip()
            except Exception:
                return SAMPLE_SCHEMA_DDL.strip()
            finally:
                if self._shared_conn is None:
                    conn.close()

    def get_schema_context(self) -> Dict[str, Any]:
        """Returns structured metadata for all tables, columns, foreign keys, and preview rows."""
        with self._lock:
            conn = self._get_connection()
            schema_info: Dict[str, Any] = {}
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;")
                tables = [row["name"] for row in cursor.fetchall()]

                for table in tables:
                    # Columns
                    cursor.execute(f'PRAGMA table_info("{table}");')
                    cols = []
                    for col in cursor.fetchall():
                        cols.append({
                            "cid": col["cid"],
                            "name": col["name"],
                            "type": col["type"] or "TEXT",
                            "notnull": bool(col["notnull"]),
                            "pk": bool(col["pk"]),
                            "dflt_value": col["dflt_value"]
                        })

                    # Foreign Keys
                    cursor.execute(f'PRAGMA foreign_key_list("{table}");')
                    fks = []
                    for fk in cursor.fetchall():
                        fks.append({
                            "id": fk["id"],
                            "table": fk["table"],
                            "from": fk["from"],
                            "to": fk["to"]
                        })

                    # Row Count & Samples
                    try:
                        cursor.execute(f'SELECT COUNT(*) FROM "{table}";')
                        total_rows = cursor.fetchone()[0]
                    except Exception:
                        total_rows = 0

                    try:
                        cursor.execute(f'SELECT * FROM "{table}" LIMIT 5;')
                        sample_rows = [list(r) for r in cursor.fetchall()]
                    except Exception:
                        sample_rows = []

                    schema_info[table] = {
                        "columns": cols,
                        "foreign_keys": fks,
                        "sample_rows": sample_rows,
                        "row_count": total_rows
                    }
            finally:
                if self._shared_conn is None:
                    conn.close()
            return schema_info

    def get_schema_summary_text(self) -> str:
        """Generates compact, human-readable schema text for LLM prompt context."""
        context = self.get_schema_context()
        lines = []
        for table, meta in context.items():
            cols = [f"{c['name']} ({c['type']}{' PK' if c['pk'] else ''})" for c in meta["columns"]]
            lines.append(f"Table `{table}`: {', '.join(cols)}")
            for fk in meta["foreign_keys"]:
                lines.append(f"  FK: `{table}.{fk['from']}` -> `{fk['table']}.{fk['to']}`")
        return "\n".join(lines)

    def execute_query(
        self,
        sql: str,
        read_only: bool = True,
        dry_run: bool = False,
        timeout_sec: float = 5.0
    ) -> Dict[str, Any]:
        """
        Executes a SQL query in the test database sandbox.
        If read_only or dry_run is True, executes in a rollback transaction to guarantee safety.
        Returns detailed execution metrics, columns, rows, execution plan, or exact error.
        """
        with self._lock:
            start_time = time.perf_counter()
            conn = self._get_connection()
            try:
                conn.execute(f"PRAGMA busy_timeout = {int(timeout_sec * 1000)};")
                cursor = conn.cursor()
                
                # Fetch explain query plan first if possible
                query_plan = []
                try:
                    plan_cursor = conn.cursor()
                    plan_cursor.execute(f"EXPLAIN QUERY PLAN {sql}")
                    for r in plan_cursor.fetchall():
                        query_plan.append({
                            "id": r[0],
                            "parent": r[1],
                            "notused": r[2],
                            "detail": r[3]
                        })
                except Exception:
                    pass

                cursor.execute(sql)
                
                # Fetch results if query returns rows
                if cursor.description:
                    columns = [col[0] for col in cursor.description]
                    rows = cursor.fetchall()
                    serializable_rows = [list(r) for r in rows[:100]] # Limit to 100 rows for preview
                    total_rows = len(rows)
                else:
                    columns = []
                    serializable_rows = []
                    total_rows = cursor.rowcount if cursor.rowcount >= 0 else 0

                # Transaction safety enforcement
                if not read_only and not dry_run:
                    conn.commit()
                else:
                    conn.rollback()

                exec_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
                return {
                    "success": True,
                    "columns": columns,
                    "rows": serializable_rows,
                    "row_count": total_rows,
                    "execution_time_ms": exec_time_ms,
                    "error": None,
                    "error_type": None,
                    "dry_run": dry_run or read_only,
                    "query_plan": query_plan
                }
            except (sqlite3.OperationalError, sqlite3.IntegrityError, sqlite3.ProgrammingError) as err:
                exec_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
                return {
                    "success": False,
                    "columns": [],
                    "rows": [],
                    "row_count": 0,
                    "execution_time_ms": exec_time_ms,
                    "error": str(err),
                    "error_type": err.__class__.__name__,
                    "dry_run": dry_run or read_only,
                    "query_plan": []
                }
            except Exception as err:
                exec_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
                return {
                    "success": False,
                    "columns": [],
                    "rows": [],
                    "row_count": 0,
                    "execution_time_ms": exec_time_ms,
                    "error": f"Execution error: {str(err)}",
                    "error_type": "GeneralExecutionError",
                    "dry_run": dry_run or read_only,
                    "query_plan": []
                }
            finally:
                if self._shared_conn is None:
                    conn.close()

    def explain_query_plan(self, sql: str) -> List[Dict[str, Any]]:
        """Runs SQLite EXPLAIN QUERY PLAN to inspect how query is parsed and executed."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(f"EXPLAIN QUERY PLAN {sql}")
                plans = []
                for row in cursor.fetchall():
                    plans.append({
                        "id": row[0],
                        "parent": row[1],
                        "notused": row[2],
                        "detail": row[3]
                    })
                return plans
            except Exception:
                return []
            finally:
                if self._shared_conn is None:
                    conn.close()


# Singleton default sandbox database instance for the session
_default_engine: Optional[DatabaseEngine] = None

def get_db_engine() -> DatabaseEngine:
    global _default_engine
    if _default_engine is None:
        _default_engine = DatabaseEngine()
    return _default_engine
