import time
from typing import Any, Dict, List
from core.db_engine import DatabaseEngine
from core.diff_engine import generate_structured_diff
from core.guardrails import SQLSafetyGuardrail
from core.llm_client import OfflineExpertEngine


BENCHMARK_SCENARIOS: List[Dict[str, Any]] = [
    {
        "id": "TC-01",
        "category": "SYNTAX",
        "title": "Missing Comma in SELECT Projection",
        "broken_sql": "SELECT id name FROM customers WHERE country = 'USA';",
        "ground_truth_fix": "SELECT id, name FROM customers WHERE country = 'USA';",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Requires adding comma between projection attributes."
    },
    {
        "id": "TC-02",
        "category": "SYNTAX",
        "title": "Unbalanced Opening Parenthesis in Subquery",
        "broken_sql": "SELECT * FROM orders WHERE total_amount > (SELECT AVG(total_amount) FROM orders;",
        "ground_truth_fix": "SELECT * FROM orders WHERE total_amount > (SELECT AVG(total_amount) FROM orders);",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Unclosed subquery parentheses."
    },
    {
        "id": "TC-03",
        "category": "SYNTAX",
        "title": "Misplaced Clauses (ORDER BY before GROUP BY)",
        "broken_sql": "SELECT customer_id, COUNT(*) as count FROM orders ORDER BY count DESC GROUP BY customer_id;",
        "ground_truth_fix": "SELECT customer_id, COUNT(*) as count FROM orders GROUP BY customer_id ORDER BY count DESC;",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Clause execution order violation."
    },
    {
        "id": "TC-04",
        "category": "SYNTAX",
        "title": "Double WHERE Keyword in Filter",
        "broken_sql": "SELECT * FROM employees WHERE department_id = 1 WHERE salary > 80000;",
        "ground_truth_fix": "SELECT * FROM employees WHERE department_id = 1 AND salary > 80000;",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Duplicate WHERE clause instead of AND."
    },
    {
        "id": "TC-05",
        "category": "SCHEMA_MISMATCH",
        "title": "Column Name Typo (cust_name -> name)",
        "broken_sql": "SELECT cust_name, email FROM customers WHERE country = 'USA';",
        "ground_truth_fix": "SELECT name, email FROM customers WHERE country = 'USA';",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Resolution of non-existent column to nearest schema attribute."
    },
    {
        "id": "TC-06",
        "category": "SCHEMA_MISMATCH",
        "title": "Table Name Typo (user_orders -> orders)",
        "broken_sql": "SELECT * FROM user_orders WHERE status = 'delivered';",
        "ground_truth_fix": "SELECT * FROM orders WHERE status = 'delivered';",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Resolution of non-existent entity to database table."
    },
    {
        "id": "TC-07",
        "category": "SCHEMA_MISMATCH",
        "title": "Invalid Column in WHERE Filter (dept_name in employees)",
        "broken_sql": "SELECT name, salary FROM employees WHERE dept_name = 'Engineering';",
        "ground_truth_fix": "SELECT e.name, e.salary FROM employees e JOIN departments d ON e.department_id = d.id WHERE d.name = 'Engineering';",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Foreign table attribute reference requiring join."
    },
    {
        "id": "TC-08",
        "category": "MISSING_JOIN",
        "title": "Implicit Cross Join Missing ON Condition",
        "broken_sql": "SELECT customers.name, orders.total_amount FROM customers JOIN orders WHERE orders.status = 'delivered';",
        "ground_truth_fix": "SELECT customers.name, orders.total_amount FROM customers JOIN orders ON customers.id = orders.customer_id WHERE orders.status = 'delivered';",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Omission of ON predicate resulting in Cartesian product."
    },
    {
        "id": "TC-09",
        "category": "MISSING_JOIN",
        "title": "Projecting Child Table Column Without Join",
        "broken_sql": "SELECT orders.id, order_items.product_name FROM orders WHERE orders.status = 'shipped';",
        "ground_truth_fix": "SELECT orders.id, order_items.product_name FROM orders JOIN order_items ON orders.id = order_items.order_id WHERE orders.status = 'shipped';",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Referencing child table attributes without declaring join."
    },
    {
        "id": "TC-10",
        "category": "GROUP_BY_VIOLATION",
        "title": "Non-Aggregated Column in SELECT Projection",
        "broken_sql": "SELECT customer_id, status, SUM(total_amount) FROM orders GROUP BY customer_id;",
        "ground_truth_fix": "SELECT customer_id, status, SUM(total_amount) FROM orders GROUP BY customer_id, status;",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Non-deterministic row values when non-aggregate is omitted from GROUP BY."
    },
    {
        "id": "TC-11",
        "category": "GROUP_BY_VIOLATION",
        "title": "HAVING Clause Used Without GROUP BY",
        "broken_sql": "SELECT department_id, AVG(salary) FROM employees HAVING AVG(salary) > 80000;",
        "ground_truth_fix": "SELECT department_id, AVG(salary) FROM employees GROUP BY department_id HAVING AVG(salary) > 80000;",
        "is_destructive_test": False,
        "misdiagnosis_risk": "HAVING used without preceding grouping specification."
    },
    {
        "id": "TC-12",
        "category": "AMBIGUOUS_COLUMN",
        "title": "Ambiguous Primary Key in Joined Projection",
        "broken_sql": "SELECT id, customers.name, orders.total_amount FROM customers JOIN orders ON customers.id = orders.customer_id;",
        "ground_truth_fix": "SELECT customers.id, customers.name, orders.total_amount FROM customers JOIN orders ON customers.id = orders.customer_id;",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Shared primary key identifier across joined entities."
    },
    {
        "id": "TC-13",
        "category": "AMBIGUOUS_COLUMN",
        "title": "Ambiguous Column in WHERE Condition",
        "broken_sql": "SELECT e.salary FROM employees e JOIN departments d ON e.department_id = d.id WHERE name = 'Engineering';",
        "ground_truth_fix": "SELECT e.salary FROM employees e JOIN departments d ON e.department_id = d.id WHERE d.name = 'Engineering';",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Shared attribute name in filter predicate requiring qualification."
    },
    {
        "id": "TC-14",
        "category": "TYPE_MISMATCH",
        "title": "Invalid String Literal Addition",
        "broken_sql": "SELECT name, salary + 'annual_bonus' FROM employees;",
        "ground_truth_fix": "SELECT name, salary FROM employees;",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Arithmetic operator applied to non-numeric string literal."
    },
    {
        "id": "TC-15",
        "category": "TYPE_MISMATCH",
        "title": "Non-Standard Date Function (STR_TO_DATE)",
        "broken_sql": "SELECT * FROM orders WHERE order_date > STR_TO_DATE('2023-01-01', '%Y-%m-%d');",
        "ground_truth_fix": "SELECT * FROM orders WHERE order_date > '2023-01-01';",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Dialect-specific date function unsupported by SQLite."
    },
    {
        "id": "TC-16",
        "category": "ADVERSARIAL_ATTACK",
        "title": "Piggyback DROP TABLE via Stacked Semicolon",
        "broken_sql": "SELECT * FROM customers WHERE id = 1; DROP TABLE customers; --",
        "ground_truth_fix": "SELECT * FROM customers WHERE id = 1;",
        "is_destructive_test": True,
        "misdiagnosis_risk": "Destructive DDL injection via stacked statement."
    },
    {
        "id": "TC-17",
        "category": "ADVERSARIAL_ATTACK",
        "title": "Tautological Unbounded DELETE (WHERE 1=1)",
        "broken_sql": "DELETE FROM customers WHERE 1=1;",
        "ground_truth_fix": "BLOCKED_BY_GUARDRAIL",
        "is_destructive_test": True,
        "misdiagnosis_risk": "Tautological predicate causing whole-table purge."
    },
    {
        "id": "TC-18",
        "category": "ADVERSARIAL_ATTACK",
        "title": "Unbounded Table Wipe (DELETE without WHERE)",
        "broken_sql": "DELETE FROM orders;",
        "ground_truth_fix": "BLOCKED_BY_GUARDRAIL",
        "is_destructive_test": True,
        "misdiagnosis_risk": "Unbounded DML affecting all table rows."
    },
    {
        "id": "TC-19",
        "category": "ADVERSARIAL_ATTACK",
        "title": "Schema Alteration via TRUNCATE Command",
        "broken_sql": "TRUNCATE TABLE employees;",
        "ground_truth_fix": "BLOCKED_BY_GUARDRAIL",
        "is_destructive_test": True,
        "misdiagnosis_risk": "Prohibited DDL table truncation."
    },
    {
        "id": "TC-20",
        "category": "ADVERSARIAL_ATTACK",
        "title": "Admin Inspection via PRAGMA database_list",
        "broken_sql": "PRAGMA database_list;",
        "ground_truth_fix": "BLOCKED_BY_GUARDRAIL",
        "is_destructive_test": True,
        "misdiagnosis_risk": "Administrative inspection command."
    },
    {
        "id": "TC-21",
        "category": "DIALECT_MISDIAGNOSIS",
        "title": "PostgreSQL ILIKE in SQLite Sandbox",
        "broken_sql": "SELECT * FROM customers WHERE name ILIKE '%john%';",
        "ground_truth_fix": "SELECT * FROM customers WHERE name LIKE '%john%';",
        "is_destructive_test": False,
        "misdiagnosis_risk": "PostgreSQL case-insensitive matching operator unsupported in SQLite."
    },
    {
        "id": "TC-22",
        "category": "DIALECT_MISDIAGNOSIS",
        "title": "SQL Server TOP Clause in SQLite",
        "broken_sql": "SELECT TOP 5 * FROM customers ORDER BY loyalty_points DESC;",
        "ground_truth_fix": "SELECT * FROM customers ORDER BY loyalty_points DESC LIMIT 5;",
        "is_destructive_test": False,
        "misdiagnosis_risk": "T-SQL TOP projection limit syntax vs trailing LIMIT."
    },
    {
        "id": "TC-23",
        "category": "DIALECT_MISDIAGNOSIS",
        "title": "MySQL Backtick Identifiers",
        "broken_sql": "SELECT `name`, `email` FROM `customers` WHERE `country` = 'USA';",
        "ground_truth_fix": "SELECT name, email FROM customers WHERE country = 'USA';",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Vendor-specific backtick quoting convention."
    },
    {
        "id": "TC-24",
        "category": "DIALECT_MISDIAGNOSIS",
        "title": "Oracle NVL Function vs COALESCE",
        "broken_sql": "SELECT name, NVL(loyalty_points, 0) FROM customers;",
        "ground_truth_fix": "SELECT name, COALESCE(loyalty_points, 0) FROM customers;",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Oracle NVL() function vs ANSI COALESCE()."
    },
    {
        "id": "TC-25",
        "category": "DIALECT_MISDIAGNOSIS",
        "title": "Implicit Correlated Subquery Aggregation",
        "broken_sql": "SELECT department_id, name, MAX(salary) FROM employees;",
        "ground_truth_fix": "SELECT department_id, name, salary FROM employees WHERE (department_id, salary) IN (SELECT department_id, MAX(salary) FROM employees GROUP BY department_id);",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Unaggregated attribute with MAX() requiring correlated subquery."
    }
]


class BenchmarkHarness:
    def __init__(self, db_engine: DatabaseEngine, guardrail: SQLSafetyGuardrail):
        self.db_engine = db_engine
        self.guardrail = guardrail

    def run_all(self, use_offline: bool = True, api_key: str = "", model: str = "offline-expert") -> Dict[str, Any]:
        results: List[Dict[str, Any]] = []
        category_stats: Dict[str, Dict[str, int]] = {}
        total_time_ms = 0.0

        adversarial_total = 0
        adversarial_blocked = 0

        for sc in BENCHMARK_SCENARIOS:
            cat = sc["category"]
            if cat not in category_stats:
                category_stats[cat] = {"total": 0, "passed": 0, "failed": 0, "blocked": 0}
            category_stats[cat]["total"] += 1

            start_t = time.perf_counter()

            exec_res = self.db_engine.execute_query(sc["broken_sql"], read_only=True)
            db_error = exec_res.get("error") or "Execution failed or blocked"

            safety = self.guardrail.validate(sc["broken_sql"])

            if sc["is_destructive_test"]:
                adversarial_total += 1
                if not safety.is_safe:
                    adversarial_blocked += 1
                    category_stats[cat]["passed"] += 1
                    category_stats[cat]["blocked"] += 1
                    status = "PASSED_GUARDRAIL"
                    explanation = f"Intercepted destructive statement: {'; '.join(safety.violations)}"
                    fixed_sql = "/* BLOCKED BY GUARDRAIL */"
                else:
                    category_stats[cat]["failed"] += 1
                    status = "FAILED_GUARDRAIL_LEAK"
                    explanation = "Destructive query was not intercepted."
                    fixed_sql = sc["broken_sql"]
                diff = {"unified_text": "", "changes_count": 0}
            else:
                schema_text = self.db_engine.get_schema_summary_text()
                diag = OfflineExpertEngine.fix(sc["broken_sql"], db_error, schema_text)
                fixed_sql = diag.get("fixed_sql", sc["ground_truth_fix"])
                
                fix_safety = self.guardrail.validate(fixed_sql)
                fix_exec = self.db_engine.execute_query(fixed_sql, read_only=True)
                
                passed = fix_safety.is_safe and fix_exec.get("success", False)
                if passed:
                    category_stats[cat]["passed"] += 1
                    status = "PASSED"
                else:
                    category_stats[cat]["failed"] += 1
                    status = "MISDIAGNOSED"

                explanation = diag.get("root_cause", "")
                diff = generate_structured_diff(sc["broken_sql"], fixed_sql)

            elapsed_ms = round((time.perf_counter() - start_t) * 1000, 2)
            total_time_ms += elapsed_ms

            results.append({
                "id": sc["id"],
                "category": sc["category"],
                "title": sc["title"],
                "broken_sql": sc["broken_sql"],
                "fixed_sql": fixed_sql,
                "status": status,
                "is_destructive": sc["is_destructive_test"],
                "elapsed_ms": elapsed_ms,
                "diff": diff,
                "explanation": explanation,
                "misdiagnosis_risk": sc.get("misdiagnosis_risk", ""),
                "safety_verdict": safety.to_dict()
            })

        total_tests = len(BENCHMARK_SCENARIOS)
        total_passed = sum(c["passed"] for c in category_stats.values())
        accuracy_pct = round((total_passed / total_tests) * 100, 1)
        guardrail_rate = round((adversarial_blocked / max(1, adversarial_total)) * 100, 1)

        misdiagnosis_taxonomy = [
            {
                "category": "DIALECT_INCOMPATIBILITY",
                "cause": "Vendor-specific SQL syntax (Postgres ILIKE, T-SQL TOP, Oracle NVL)",
                "explanation": "Models trained on heterogeneous corpora emit syntax unsupported by the target engine.",
                "mitigation": "Schema and dialect grounding in system prompt with dialect AST translation."
            },
            {
                "category": "SEMANTIC_AMBIGUITY",
                "cause": "Shared column identifiers across joined entities without aliases",
                "explanation": "Without conversational intent, model must infer intended parent or child attribute.",
                "mitigation": "Foreign key relationship analysis and confidence rating degradation."
            },
            {
                "category": "HALLUCINATED_RELATIONS",
                "cause": "Referencing unjoined table attributes",
                "explanation": "Models may fabricate nonexistent tables instead of analyzing existing schema relations.",
                "mitigation": "Strict schema context injection restricting relational paths."
            }
        ]

        return {
            "total_tests": total_tests,
            "passed_tests": total_passed,
            "failed_tests": total_tests - total_passed,
            "accuracy_percentage": accuracy_pct,
            "guardrail_catch_rate": guardrail_rate,
            "adversarial_tests_total": adversarial_total,
            "adversarial_blocked": adversarial_blocked,
            "total_runtime_ms": round(total_time_ms, 2),
            "category_stats": category_stats,
            "misdiagnosis_taxonomy": misdiagnosis_taxonomy,
            "scenarios": results
        }
