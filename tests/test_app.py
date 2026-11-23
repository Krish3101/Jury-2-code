"""
Consolidated Unit Tests for SQL Error Explainer & Fixer
Tests DB engine, guardrails, diff engine, offline expert, and REST API endpoints.
"""

import json
import unittest
from io import BytesIO
from unittest.mock import MagicMock

from core.db_engine import DatabaseEngine
from core.diff_engine import generate_structured_diff, generate_unified_diff
from core.guardrails import SQLSafetyGuardrail
from core.llm_client import OfflineExpertEngine, OpenRouterLLMClient
from web.server import RequestHandler


class TestDatabaseEngine(unittest.TestCase):
    def setUp(self):
        self.db = DatabaseEngine(":memory:")

    def tearDown(self):
        self.db.close()

    def test_schema_initialization(self):
        context = self.db.get_schema_context()
        self.assertIn("customers", context)
        self.assertIn("orders", context)
        self.assertIn("order_items", context)
        self.assertIn("employees", context)
        self.assertIn("departments", context)
        self.assertGreater(context["customers"]["row_count"], 0)

    def test_successful_query(self):
        res = self.db.execute_query("SELECT id, name FROM customers WHERE country = 'USA';")
        self.assertTrue(res["success"])
        self.assertIsNone(res["error"])
        self.assertEqual(res["columns"], ["id", "name"])
        self.assertGreater(len(res["rows"]), 0)

    def test_broken_query_captures_error(self):
        res = self.db.execute_query("SELECT * FROM non_existent_table;")
        self.assertFalse(res["success"])
        self.assertIsNotNone(res["error"])
        self.assertIn("no such table", res["error"].lower())

    def test_explain_query_plan(self):
        plan = self.db.explain_query_plan("SELECT * FROM customers WHERE id = 1;")
        self.assertIsInstance(plan, list)


class TestSQLSafetyGuardrail(unittest.TestCase):
    def setUp(self):
        self.guard = SQLSafetyGuardrail()

    def test_safe_select(self):
        verdict = self.guard.validate("SELECT * FROM customers WHERE id = 1;")
        self.assertTrue(verdict.is_safe)
        self.assertEqual(verdict.risk_level, "SAFE")
        self.assertEqual(len(verdict.violations), 0)

    def test_block_drop_table(self):
        verdict = self.guard.validate("DROP TABLE customers;")
        self.assertFalse(verdict.is_safe)
        self.assertEqual(verdict.risk_level, "CRITICAL")
        self.assertTrue(any("DROP" in v for v in verdict.violations))

    def test_block_unbounded_delete(self):
        verdict = self.guard.validate("DELETE FROM customers;")
        self.assertFalse(verdict.is_safe)
        self.assertEqual(verdict.risk_level, "CRITICAL")
        self.assertTrue(any("Unbounded" in v for v in verdict.violations))

    def test_block_trivial_where_delete(self):
        verdict = self.guard.validate("DELETE FROM customers WHERE 1=1;")
        self.assertFalse(verdict.is_safe)
        self.assertEqual(verdict.risk_level, "CRITICAL")
        self.assertTrue(any("Trivial/tautological" in v for v in verdict.violations))

    def test_block_stacked_injection(self):
        verdict = self.guard.validate("SELECT * FROM customers; DROP TABLE orders;")
        self.assertFalse(verdict.is_safe)
        self.assertEqual(verdict.statement_type, "MULTI_STATEMENT")
        self.assertTrue(any("Stacked multi-statement" in v for v in verdict.violations))


class TestDiffEngine(unittest.TestCase):
    def test_diff_generation(self):
        orig = "SELECT id name FROM customers"
        fixed = "SELECT id, name FROM customers"
        diff = generate_structured_diff(orig, fixed)
        self.assertIn("unified_text", diff)
        self.assertGreater(diff["changes_count"], 0)

    def test_unified_diff_newlines(self):
        orig = "SELECT id name FROM customers;"
        fixed = "SELECT id, name FROM customers;"
        udiff = generate_unified_diff(orig, fixed)
        self.assertIn("--- Original Broken SQL\n", udiff)
        self.assertIn("+++ Corrected SQL\n", udiff)
        self.assertIn("-SELECT id name FROM customers;\n", udiff)
        self.assertIn("+SELECT id, name FROM customers;\n", udiff)


class TestOfflineExpertEngine(unittest.TestCase):
    def setUp(self):
        self.db = DatabaseEngine(":memory:")
        self.guard = SQLSafetyGuardrail()
        self.llm = OpenRouterLLMClient(model="offline-expert")

    def tearDown(self):
        self.db.close()

    def test_offline_syntax_fix(self):
        diag, _ = self.llm.generate_fix(
            "SELECT id name FROM customers;",
            "near \"name\": syntax error",
            self.db.get_schema_summary_text(),
            force_offline=True
        )
        self.assertIn("fixed_sql", diag)
        self.assertIn("SELECT id, name FROM", diag["fixed_sql"])

    def test_offline_missing_join_on(self):
        diag, _ = self.llm.generate_fix(
            "SELECT * FROM orders JOIN customers WHERE status = 'delivered';",
            "",
            self.db.get_schema_summary_text(),
            force_offline=True
        )
        self.assertIn("fixed_sql", diag)
        self.assertIn("ON orders.customer_id = customers.id", diag["fixed_sql"])
        res = self.db.execute_query(diag["fixed_sql"])
        self.assertTrue(res["success"])
        self.assertEqual(res["row_count"], 6)

    def test_offline_valid_query_diagnosis(self):
        diag, _ = self.llm.generate_fix(
            "SELECT id, name FROM customers;",
            "",
            self.db.get_schema_summary_text(),
            force_offline=True
        )
        self.assertEqual(diag["error_category"], "VALID_QUERY")
        self.assertEqual(diag["confidence"], 1.0)

    def test_offline_integrity_constraint(self):
        diag = OfflineExpertEngine.fix(
            "INSERT INTO order_items (quantity) VALUES (-1);",
            "CHECK constraint failed: quantity > 0",
            self.db.get_schema_summary_text()
        )
        self.assertEqual(diag["error_category"], "INTEGRITY_VIOLATION")


class DummyRequest:
    def makefile(self, *args, **kwargs):
        return BytesIO(b"")


class TestServerEndpoints(unittest.TestCase):
    def _create_handler(self, path: str, method: str = "GET", body: dict = None):
        request = DummyRequest()
        client_address = ("127.0.0.1", 8080)
        server = MagicMock()

        handler = RequestHandler.__new__(RequestHandler)
        handler.client_address = client_address
        handler.server = server
        handler.request = request
        handler.path = path
        handler.command = method
        handler.requestline = f"{method} {path} HTTP/1.1"
        handler.request_version = "HTTP/1.1"
        handler.headers = {"Content-Length": str(len(json.dumps(body))) if body else "0"}
        handler.rfile = BytesIO(json.dumps(body).encode("utf-8") if body else b"")
        handler.wfile = BytesIO()
        handler.close_connection = True
        return handler

    def test_get_schema_endpoint(self):
        handler = self._create_handler("/api/schema", "GET")
        handler.do_GET()
        output = handler.wfile.getvalue().decode("utf-8")
        self.assertIn("HTTP/1.0 200 OK", output)
        self.assertIn("customers", output)

    def test_get_benchmarks_endpoint(self):
        handler = self._create_handler("/api/benchmarks", "GET")
        handler.do_GET()
        output = handler.wfile.getvalue().decode("utf-8")
        self.assertIn("HTTP/1.0 200 OK", output)
        self.assertIn("benchmarks", output)

    def test_post_run_sql_endpoint(self):
        handler = self._create_handler("/api/run-sql", "POST", {"sql": "SELECT * FROM customers;"})
        handler.do_POST()
        output = handler.wfile.getvalue().decode("utf-8")
        self.assertIn("HTTP/1.0 200 OK", output)
        self.assertIn('"success": true', output)

    def test_post_guardrail_blocked_sql(self):
        handler = self._create_handler("/api/run-sql", "POST", {"sql": "DROP TABLE customers;"})
        handler.do_POST()
        output = handler.wfile.getvalue().decode("utf-8")
        self.assertIn("HTTP/1.0 200 OK", output)
        self.assertIn('"guardrail_blocked": true', output)

    def test_post_explain_and_fix(self):
        handler = self._create_handler("/api/explain-and-fix", "POST", {
            "sql": "SELECT id name email FROM customers;",
            "force_offline": True
        })
        handler.do_POST()
        output = handler.wfile.getvalue().decode("utf-8")
        self.assertIn("HTTP/1.0 200 OK", output)
        self.assertIn("fixed_sql", output)
        self.assertIn("SELECT id, name, email FROM customers;", output)

    def test_post_malformed_json_returns_400(self):
        handler = self._create_handler("/api/run-sql", "POST", body=None)
        handler.headers = {"Content-Length": "12"}
        handler.rfile = BytesIO(b"{bad json!!}")
        handler.do_POST()
        output = handler.wfile.getvalue().decode("utf-8")
        self.assertIn("HTTP/1.0 400 Bad Request", output)
        self.assertIn("Malformed", output)


if __name__ == "__main__":
    unittest.main()
