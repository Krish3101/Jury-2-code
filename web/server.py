"""
Web Server for SQL Error Explainer & Fixer
Provides multi-threaded HTTP REST API and serves the Single-Page Application interface.
Uses Python Standard Library (zero external dependencies).
"""

import http.server
import json
import mimetypes
import os
import sys
import urllib.parse
from typing import Any, Dict

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.db_engine import get_db_engine
from core.diff_engine import generate_structured_diff
from core.guardrails import get_guardrail
from core.llm_client import OpenRouterLLMClient

PRESET_SCENARIOS = [
    {
        "id": "TC-01",
        "category": "SYNTAX",
        "title": "Missing Comma in SELECT Projection",
        "description": "Two column names separated by space instead of a comma delimiter.",
        "broken_sql": "SELECT id name FROM customers WHERE country = 'USA';",
        "is_destructive_test": False
    },
    {
        "id": "TC-02",
        "category": "SYNTAX",
        "title": "Unbalanced Opening Parenthesis",
        "description": "Subquery comparison opened with a parenthesis that is never closed.",
        "broken_sql": "SELECT * FROM orders WHERE total_amount > (SELECT AVG(total_amount) FROM orders;",
        "is_destructive_test": False
    },
    {
        "id": "TC-03",
        "category": "SYNTAX",
        "title": "Misplaced SQL Clauses (ORDER BY before GROUP BY)",
        "description": "ORDER BY clause positioned before GROUP BY, violating standard clause execution order.",
        "broken_sql": "SELECT customer_id, COUNT(*) as count FROM orders ORDER BY count DESC GROUP BY customer_id;",
        "is_destructive_test": False
    },
    {
        "id": "TC-04",
        "category": "SCHEMA_MISMATCH",
        "title": "Non-Existent Column Name (Typo)",
        "description": "Column 'cust_name' does not exist on table 'customers' (correct column is 'name').",
        "broken_sql": "SELECT id, cust_name, email FROM customers;",
        "is_destructive_test": False
    },
    {
        "id": "TC-05",
        "category": "SCHEMA_MISMATCH",
        "title": "Non-Existent Table (Synonym Misuse)",
        "description": "Table 'users' referenced instead of the schema table 'customers'.",
        "broken_sql": "SELECT id, name FROM users WHERE country = 'USA';",
        "is_destructive_test": False
    },
    {
        "id": "TC-06",
        "category": "AMBIGUOUS_COLUMN",
        "title": "Ambiguous Column in Multi-Table JOIN",
        "description": "Column 'id' exists on both 'orders' and 'customers' without table qualifier.",
        "broken_sql": "SELECT id, total_amount, name FROM orders JOIN customers ON orders.customer_id = customers.id;",
        "is_destructive_test": False
    },
    {
        "id": "TC-07",
        "category": "GROUP_BY_VIOLATION",
        "title": "Omitted Non-Aggregated Column in GROUP BY",
        "description": "Column 'status' selected without being included in GROUP BY clause.",
        "broken_sql": "SELECT status, customer_id, SUM(total_amount) FROM orders GROUP BY customer_id;",
        "is_destructive_test": False
    },
    {
        "id": "TC-08",
        "category": "TYPE_MISMATCH",
        "title": "Arithmetic Operator Used for String Concatenation",
        "description": "Using '+' operator for string concatenation instead of SQLite '||'.",
        "broken_sql": "SELECT name + ' (' + email + ')' AS contact_info FROM customers;",
        "is_destructive_test": False
    },
    {
        "id": "TC-09",
        "category": "SCHEMA_MISMATCH",
        "title": "Foreign Key Column Typo in Filtering",
        "description": "Column 'dept_id' does not exist on 'employees' (correct column is 'department_id').",
        "broken_sql": "SELECT * FROM employees WHERE dept_id = 2;",
        "is_destructive_test": False
    },
    {
        "id": "TC-10",
        "category": "SYNTAX",
        "title": "Missing JOIN ON Predicate",
        "description": "JOIN clause without an ON condition.",
        "broken_sql": "SELECT * FROM orders JOIN customers WHERE status = 'delivered';",
        "is_destructive_test": False
    },
    {
        "id": "TC-11",
        "category": "HAZARD_GUARD",
        "title": "Destructive Schema Teardown (DROP TABLE)",
        "description": "Attempt to drop the customers table, triggering AST guardrails.",
        "broken_sql": "DROP TABLE customers;",
        "is_destructive_test": True
    },
    {
        "id": "TC-12",
        "category": "HAZARD_GUARD",
        "title": "Unbounded Table Wipe (DELETE without WHERE)",
        "description": "Unbounded DELETE statement that would wipe the entire table.",
        "broken_sql": "DELETE FROM customers;",
        "is_destructive_test": True
    }
]


STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


class RequestHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Clean terminal logging
        sys.stderr.write(f"[{self.log_date_time_string()}] {format % args}\n")

    def _send_json(self, data: Any, status: int = 200):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # REST API Routes
        if path == "/api/schema":
            db = get_db_engine()
            context = db.get_schema_context()
            self._send_json({"schema": context, "ddl": db.get_schema_ddl()})
            return

        elif path == "/api/benchmarks":
            self._send_json({"benchmarks": PRESET_SCENARIOS})
            return

        # Static File Serving
        if path == "/" or path == "":
            file_path = os.path.join(STATIC_DIR, "index.html")
        else:
            rel_path = path.lstrip("/")
            file_path = os.path.join(STATIC_DIR, rel_path)

        # Normalize and ensure no directory traversal
        norm_file_path = os.path.normpath(file_path)
        if not norm_file_path.startswith(STATIC_DIR) or not os.path.isfile(norm_file_path):
            self.send_error(404, "File Not Found")
            return

        mime_type, _ = mimetypes.guess_type(norm_file_path)
        mime_type = mime_type or "application/octet-stream"

        try:
            with open(norm_file_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(500, f"Error reading file: {str(e)}")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        try:
            payload = json.loads(body) if body else {}
        except Exception:
            self._send_json({"error": "Malformed or invalid JSON payload."}, status=400)
            return

        db = get_db_engine()
        guard = get_guardrail()

        if path == "/api/run-sql":
            sql = payload.get("sql", "").strip()
            allow_dml = bool(payload.get("allow_dml", False))

            # Guardrail check
            verdict = guard.validate(sql, allow_dml=allow_dml)
            if not verdict.is_safe and verdict.risk_level == "CRITICAL":
                self._send_json({
                    "success": False,
                    "guardrail_blocked": True,
                    "verdict": verdict.to_dict(),
                    "error": f"Execution Blocked by Guardrail: {'; '.join(verdict.violations)}"
                })
                return

            exec_res = db.execute_query(sql, read_only=not allow_dml)
            exec_res["guardrail_blocked"] = False
            exec_res["verdict"] = verdict.to_dict()
            self._send_json(exec_res)
            return

        elif path == "/api/explain-and-fix":
            broken_sql = payload.get("sql", "").strip()
            api_key = payload.get("api_key", "").strip()
            model = payload.get("model", "openrouter/free").strip()
            force_offline = bool(payload.get("force_offline", False))

            # Step 1: Pre-execution guardrail check on broken input
            verdict = guard.validate(broken_sql)
            if not verdict.is_safe and verdict.risk_level == "CRITICAL":
                self._send_json({
                    "is_destructive_input": True,
                    "verdict": verdict.to_dict(),
                    "diagnosis": {
                        "root_cause": "The input query is a prohibited or destructive statement flagged by safety guardrails.",
                        "technical_details": f"Guardrail violations: {'; '.join(verdict.violations)}",
                        "error_category": "HAZARD_BLOCKED",
                        "fixed_sql": "-- Prohibited operation blocked. No destructive query permitted.",
                        "diff_explanation": "Execution aborted to protect database integrity.",
                        "confidence": 1.0,
                        "prevention_advice": verdict.remediation_advice
                    },
                    "diff": {
                        "unified_text": "Execution Blocked",
                        "left_lines": [],
                        "right_lines": [],
                        "changes_count": 0
                    },
                    "fixed_execution": {
                        "success": False,
                        "error": "Destructive query blocked by guardrails.",
                        "columns": [],
                        "rows": [],
                        "row_count": 0,
                        "execution_time_ms": 0
                    },
                    "model_used": "AST Safety Guardrail"
                })
                return

            # Step 2: Execute broken query in DB sandbox to capture exact error
            broken_exec = db.execute_query(broken_sql)
            raw_error = broken_exec["error"] or "Query executed without syntax error. Inspect semantic/aggregation logic."

            # Step 3: Prompt LLM or Offline Expert Engine
            llm = OpenRouterLLMClient(api_key=api_key, model=model)
            schema_text = db.get_schema_summary_text()
            diagnosis, model_used = llm.generate_fix(
                broken_sql,
                raw_error,
                schema_text,
                force_offline=force_offline
            )
            fixed_sql = diagnosis.get("fixed_sql", "").strip()

            # Step 4: Validate proposed fix with Guardrails
            fix_verdict = guard.validate(fixed_sql)
            if not fix_verdict.is_safe and fix_verdict.risk_level == "CRITICAL":
                self._send_json({
                    "is_destructive_fix": True,
                    "verdict": fix_verdict.to_dict(),
                    "diagnosis": diagnosis,
                    "diff": generate_structured_diff(broken_sql, fixed_sql),
                    "fixed_execution": {
                        "success": False,
                        "error": f"Guardrail blocked proposed fix: {'; '.join(fix_verdict.violations)}",
                        "columns": [],
                        "rows": [],
                        "row_count": 0,
                        "execution_time_ms": 0
                    },
                    "model_used": model_used
                })
                return

            # Step 5: Execute proposed fix in DB sandbox
            fixed_exec = db.execute_query(fixed_sql)
            query_plan = db.explain_query_plan(fixed_sql) if fixed_exec["success"] else []

            # Step 6: Compute structured diff
            diff_data = generate_structured_diff(broken_sql, fixed_sql)

            self._send_json({
                "broken_sql": broken_sql,
                "broken_error": broken_exec["error"],
                "diagnosis": diagnosis,
                "diff": diff_data,
                "fixed_sql": fixed_sql,
                "fixed_execution": fixed_exec,
                "query_plan": query_plan,
                "verdict": fix_verdict.to_dict(),
                "model_used": model_used
            })
            return

        elif path == "/api/reset-db":
            db.reset_database()
            self._send_json({"success": True, "message": "Database reset to pristine state."})
            return

        self.send_error(404, "API endpoint not found")


def start_server(port: int = 8080):
    server_address = ("", port)
    httpd = http.server.ThreadingHTTPServer(server_address, RequestHandler)
    print("=" * 70)
    print(f" SQL Error Explainer & Fixer Server Started")
    print(f" Web UI URL : http://localhost:{port}")
    print(f" API Endpoints : http://localhost:{port}/api/schema")
    print(f" Model Engine : OpenRouter API / Offline Expert Engine")
    print("=" * 70)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        httpd.server_close()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    start_server(port)
