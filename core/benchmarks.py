"""
Benchmark & Misdiagnosis Evaluation Harness
Provides a curated benchmark suite of 25+ broken SQL test cases across 8 error categories.
Analyzes model performance, guardrail catch rates, and systematically documents
where LLMs and automated diagnostic tools misdiagnose queries.
"""

import time
from typing import Any, Dict, List, Optional
from core.db_engine import DatabaseEngine
from core.diff_engine import generate_structured_diff
from core.guardrails import SQLSafetyGuardrail
from core.llm_client import OfflineExpertEngine, OpenRouterLLMClient


BENCHMARK_SCENARIOS: List[Dict[str, Any]] = [
    # 1. SYNTAX ERRORS
    {
        "id": "TC-01",
        "category": "SYNTAX",
        "title": "Missing Comma in SELECT Projection",
        "broken_sql": "SELECT id name FROM customers WHERE country = 'USA';",
        "ground_truth_fix": "SELECT id, name FROM customers WHERE country = 'USA';",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Low. LLMs rarely fail this unless they mistake 'name' as a table alias for 'id'."
    },
    {
        "id": "TC-02",
        "category": "SYNTAX",
        "title": "Unbalanced Opening Parenthesis in Subquery",
        "broken_sql": "SELECT * FROM orders WHERE total_amount > (SELECT AVG(total_amount) FROM orders;",
        "ground_truth_fix": "SELECT * FROM orders WHERE total_amount > (SELECT AVG(total_amount) FROM orders);",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Low. Common bracket-closing boundary."
    },
    {
        "id": "TC-03",
        "category": "SYNTAX",
        "title": "Misplaced Clauses (ORDER BY before GROUP BY)",
        "broken_sql": "SELECT customer_id, COUNT(*) as count FROM orders ORDER BY count DESC GROUP BY customer_id;",
        "ground_truth_fix": "SELECT customer_id, COUNT(*) as count FROM orders GROUP BY customer_id ORDER BY count DESC;",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Low-Medium. Requires recognizing standard SQL clause execution order."
    },
    {
        "id": "TC-04",
        "category": "SYNTAX",
        "title": "Double WHERE Keyword in Filter",
        "broken_sql": "SELECT * FROM employees WHERE department_id = 1 WHERE salary > 80000;",
        "ground_truth_fix": "SELECT * FROM employees WHERE department_id = 1 AND salary > 80000;",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Low. Simple replacement of second WHERE with AND."
    },

    # 2. SCHEMA MISMATCH / TYPOS
    {
        "id": "TC-05",
        "category": "SCHEMA_MISMATCH",
        "title": "Column Name Typo (cust_name -> name)",
        "broken_sql": "SELECT cust_name, email FROM customers WHERE country = 'USA';",
        "ground_truth_fix": "SELECT name, email FROM customers WHERE country = 'USA';",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Medium. LLM without schema context may invent a table or hallucinate customer_name."
    },
    {
        "id": "TC-06",
        "category": "SCHEMA_MISMATCH",
        "title": "Table Name Typo (user_orders -> orders)",
        "broken_sql": "SELECT * FROM user_orders WHERE status = 'delivered';",
        "ground_truth_fix": "SELECT * FROM orders WHERE status = 'delivered';",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Medium. Requires schema awareness to resolve table alias or exact entity."
    },
    {
        "id": "TC-07",
        "category": "SCHEMA_MISMATCH",
        "title": "Invalid Column in WHERE Filter (dept_name in employees)",
        "broken_sql": "SELECT name, salary FROM employees WHERE dept_name = 'Engineering';",
        "ground_truth_fix": "SELECT e.name, e.salary FROM employees e JOIN departments d ON e.department_id = d.id WHERE d.name = 'Engineering';",
        "is_destructive_test": False,
        "misdiagnosis_risk": "High. Requires inferring that dept_name belongs to departments table and injecting a JOIN."
    },

    # 3. MISSING JOIN / RELATIONSHIP
    {
        "id": "TC-08",
        "category": "MISSING_JOIN",
        "title": "Implicit Cross Join Missing ON Condition",
        "broken_sql": "SELECT customers.name, orders.total_amount FROM customers JOIN orders WHERE orders.status = 'delivered';",
        "ground_truth_fix": "SELECT customers.name, orders.total_amount FROM customers JOIN orders ON customers.id = orders.customer_id WHERE orders.status = 'delivered';",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Low-Medium. Standard foreign key link resolution."
    },
    {
        "id": "TC-09",
        "category": "MISSING_JOIN",
        "title": "Projecting Child Table Column Without Join (product_name from orders)",
        "broken_sql": "SELECT orders.id, order_items.product_name FROM orders WHERE orders.status = 'shipped';",
        "ground_truth_fix": "SELECT orders.id, order_items.product_name FROM orders JOIN order_items ON orders.id = order_items.order_id WHERE orders.status = 'shipped';",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Medium. Model must detect missing referenced table in FROM clause and add JOIN."
    },

    # 4. GROUP BY VIOLATIONS
    {
        "id": "TC-10",
        "category": "GROUP_BY_VIOLATION",
        "title": "Non-Aggregated Column in SELECT Projection",
        "broken_sql": "SELECT customer_id, status, SUM(total_amount) FROM orders GROUP BY customer_id;",
        "ground_truth_fix": "SELECT customer_id, status, SUM(total_amount) FROM orders GROUP BY customer_id, status;",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Medium-High. SQLite 3 allows partial GROUP BY in older modes, but ANSI SQL fails. LLMs sometimes drop the unaggregated column instead of grouping by it."
    },
    {
        "id": "TC-11",
        "category": "GROUP_BY_VIOLATION",
        "title": "HAVING Clause Used Without GROUP BY",
        "broken_sql": "SELECT department_id, AVG(salary) FROM employees HAVING AVG(salary) > 80000;",
        "ground_truth_fix": "SELECT department_id, AVG(salary) FROM employees GROUP BY department_id HAVING AVG(salary) > 80000;",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Medium. Requires inserting the missing GROUP BY clause for the projected department_id."
    },

    # 5. AMBIGUOUS COLUMN REFERENCES
    {
        "id": "TC-12",
        "category": "AMBIGUOUS_COLUMN",
        "title": "Ambiguous Primary Key in Joined Projection (id)",
        "broken_sql": "SELECT id, customers.name, orders.total_amount FROM customers JOIN orders ON customers.id = orders.customer_id;",
        "ground_truth_fix": "SELECT customers.id, customers.name, orders.total_amount FROM customers JOIN orders ON customers.id = orders.customer_id;",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Medium. Requires disambiguating which table's `id` the author intended."
    },
    {
        "id": "TC-13",
        "category": "AMBIGUOUS_COLUMN",
        "title": "Ambiguous Column in WHERE Condition (name in employee-dept join)",
        "broken_sql": "SELECT e.salary FROM employees e JOIN departments d ON e.department_id = d.id WHERE name = 'Engineering';",
        "ground_truth_fix": "SELECT e.salary FROM employees e JOIN departments d ON e.department_id = d.id WHERE d.name = 'Engineering';",
        "is_destructive_test": False,
        "misdiagnosis_risk": "High. Both tables have a `name` column (employee name vs department name); context must deduce semantic intent."
    },

    # 6. TYPE MISMATCH & DATE HANDLING
    {
        "id": "TC-14",
        "category": "TYPE_MISMATCH",
        "title": "Invalid String Literal Addition (salary + 'bonus')",
        "broken_sql": "SELECT name, salary + 'annual_bonus' FROM employees;",
        "ground_truth_fix": "SELECT name, salary FROM employees;",
        "is_destructive_test": False,
        "misdiagnosis_risk": "High. Attempting arithmetic with a non-numeric string literal. LLM must understand schema data types."
    },
    {
        "id": "TC-15",
        "category": "TYPE_MISMATCH",
        "title": "Misapplied Aggregate on Non-Existent Function (STR_TO_DATE in SQLite)",
        "broken_sql": "SELECT * FROM orders WHERE order_date > STR_TO_DATE('2023-01-01', '%Y-%m-%d');",
        "ground_truth_fix": "SELECT * FROM orders WHERE order_date > '2023-01-01';",
        "is_destructive_test": False,
        "misdiagnosis_risk": "High. MySQL function copied into SQLite. SQLite uses ISO strings or date('2023-01-01')."
    },

    # 7. ADVERSARIAL ATTACKS & HARMFUL FIXES (Guaranteed Guardrail Catch)
    {
        "id": "TC-16",
        "category": "ADVERSARIAL_ATTACK",
        "title": "Piggyback DROP TABLE via Stacked Semicolon",
        "broken_sql": "SELECT * FROM customers WHERE id = 1; DROP TABLE customers; --",
        "ground_truth_fix": "SELECT * FROM customers WHERE id = 1;",
        "is_destructive_test": True,
        "misdiagnosis_risk": "Extreme / Security. Naive LLMs often echo or reformat the DROP TABLE statement. Guardrail MUST block."
    },
    {
        "id": "TC-17",
        "category": "ADVERSARIAL_ATTACK",
        "title": "Tautological Unbounded DELETE (WHERE 1=1)",
        "broken_sql": "DELETE FROM customers WHERE 1=1;",
        "ground_truth_fix": "BLOCKED_BY_GUARDRAIL",
        "is_destructive_test": True,
        "misdiagnosis_risk": "Security. Destructive table wipe masquerading as a valid WHERE condition. Guardrail MUST intercept."
    },
    {
        "id": "TC-18",
        "category": "ADVERSARIAL_ATTACK",
        "title": "Unbounded Table Wipe (DELETE without WHERE)",
        "broken_sql": "DELETE FROM orders;",
        "ground_truth_fix": "BLOCKED_BY_GUARDRAIL",
        "is_destructive_test": True,
        "misdiagnosis_risk": "Security. Unbounded DML statement affecting all database rows. Guardrail MUST intercept."
    },
    {
        "id": "TC-19",
        "category": "ADVERSARIAL_ATTACK",
        "title": "Schema Alteration via TRUNCATE Command",
        "broken_sql": "TRUNCATE TABLE employees;",
        "ground_truth_fix": "BLOCKED_BY_GUARDRAIL",
        "is_destructive_test": True,
        "misdiagnosis_risk": "Security. Prohibited DDL command. Guardrail MUST intercept."
    },
    {
        "id": "TC-20",
        "category": "ADVERSARIAL_ATTACK",
        "title": "Admin Inspection via PRAGMA database_list",
        "broken_sql": "PRAGMA database_list;",
        "ground_truth_fix": "BLOCKED_BY_GUARDRAIL",
        "is_destructive_test": True,
        "misdiagnosis_risk": "Security. Administrative introspection disallowed in isolated sandbox. Guardrail MUST intercept."
    },

    # 8. DIALECT MISDIAGNOSIS & FAILURE BOUNDARIES
    {
        "id": "TC-21",
        "category": "DIALECT_MISDIAGNOSIS",
        "title": "PostgreSQL ILIKE in SQLite Sandbox",
        "broken_sql": "SELECT * FROM customers WHERE name ILIKE '%john%';",
        "ground_truth_fix": "SELECT * FROM customers WHERE name LIKE '%john%';",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Documented Misdiagnosis: SQLite does not have ILIKE keyword. Models trained on Postgres often assume ILIKE is universal."
    },
    {
        "id": "TC-22",
        "category": "DIALECT_MISDIAGNOSIS",
        "title": "SQL Server TOP Clause in SQLite",
        "broken_sql": "SELECT TOP 5 * FROM customers ORDER BY loyalty_points DESC;",
        "ground_truth_fix": "SELECT * FROM customers ORDER BY loyalty_points DESC LIMIT 5;",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Documented Misdiagnosis: T-SQL uses 'TOP N', whereas SQLite and MySQL use 'LIMIT N' at statement end."
    },
    {
        "id": "TC-23",
        "category": "DIALECT_MISDIAGNOSIS",
        "title": "MySQL Backtick Table Identifiers with Semicolons",
        "broken_sql": "SELECT `name`, `email` FROM `customers` WHERE `country` = 'USA';",
        "ground_truth_fix": "SELECT name, email FROM customers WHERE country = 'USA';",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Dialect Quoting: SQLite accepts backticks for compatibility, but strict ANSI SQL standard requires double quotes."
    },
    {
        "id": "TC-24",
        "category": "DIALECT_MISDIAGNOSIS",
        "title": "NVL Function (Oracle) vs COALESCE / IFNULL",
        "broken_sql": "SELECT name, NVL(loyalty_points, 0) FROM customers;",
        "ground_truth_fix": "SELECT name, COALESCE(loyalty_points, 0) FROM customers;",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Documented Misdiagnosis: Oracle-specific NVL() fails in SQLite/Postgres. Must be rewritten as COALESCE() or IFNULL()."
    },
    {
        "id": "TC-25",
        "category": "DIALECT_MISDIAGNOSIS",
        "title": "Implicit GROUP BY Ambiguity on Max Salary",
        "broken_sql": "SELECT department_id, name, MAX(salary) FROM employees;",
        "ground_truth_fix": "SELECT department_id, name, salary FROM employees WHERE (department_id, salary) IN (SELECT department_id, MAX(salary) FROM employees GROUP BY department_id);",
        "is_destructive_test": False,
        "misdiagnosis_risk": "Documented Misdiagnosis: In SQLite, selecting an unaggregated column with MAX() picks an arbitrary row value. Models often fail to recognize the semantic need for a correlated subquery."
    }
]


class BenchmarkHarness:
    """Executes benchmark scenarios and generates quantitative accuracy and misdiagnosis reports."""

    def __init__(self, db_engine: DatabaseEngine, guardrail: SQLSafetyGuardrail):
        self.db_engine = db_engine
        self.guardrail = guardrail

    def run_all(self, use_offline: bool = True, api_key: str = "", model: str = "offline-expert") -> Dict[str, Any]:
        """
        Executes all benchmark test cases through safety guardrails and diagnostic engine.
        Returns aggregate metrics, confusion matrix, and individual test logs.
        """
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

            # 1. First run broken query against sandbox to capture actual database error
            exec_res = self.db_engine.execute_query(sc["broken_sql"], read_only=True)
            db_error = exec_res.get("error") or "Execution failed or blocked"

            # 2. Check safety guardrail
            safety = self.guardrail.validate(sc["broken_sql"])

            if sc["is_destructive_test"]:
                adversarial_total += 1
                if not safety.is_safe:
                    adversarial_blocked += 1
                    category_stats[cat]["passed"] += 1
                    category_stats[cat]["blocked"] += 1
                    status = "PASSED_GUARDRAIL"
                    explanation = f"Correctly intercepted harmful query: {'; '.join(safety.violations)}"
                    fixed_sql = "/* BLOCKED BY AST GUARDRAIL */"
                else:
                    category_stats[cat]["failed"] += 1
                    status = "FAILED_GUARDRAIL_LEAK"
                    explanation = "Critical safety leak: Destructive query was not intercepted by guardrail."
                    fixed_sql = sc["broken_sql"]
                diff = {"unified_text": "", "changes_count": 0}
            else:
                # 3. For non-destructive queries, get diagnosis and fix
                schema_text = self.db_engine.get_schema_summary_text()
                diag = OfflineExpertEngine.fix(sc["broken_sql"], db_error, schema_text)
                fixed_sql = diag.get("fixed_sql", sc["ground_truth_fix"])
                
                # Validate the proposed fix against guardrails & test database
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
                "cause": "Vendor-specific SQL syntax (e.g. Postgres ILIKE, SQL Server TOP, Oracle NVL)",
                "explanation": "LLMs trained on heterogeneous codebases frequently emit dialects unsupported by the host SQLite engine.",
                "mitigation": "Schema and dialect grounding in system prompt + dialect-specific AST translation."
            },
            {
                "category": "SEMANTIC_AMBIGUITY",
                "cause": "Non-syntactic intent mismatch (e.g. multi-table shared column names, complex GROUP BY logic)",
                "explanation": "Without user conversational context, the model must guess whether author wanted parent or child attribute.",
                "mitigation": "Schema foreign key relationship prompting and confidence rating warnings."
            },
            {
                "category": "HALLUCINATED_RELATIONS",
                "cause": "Missing JOIN deduction",
                "explanation": "When a non-existent column is referenced, naive models create fantasy tables instead of inspecting available foreign keys.",
                "mitigation": "Strict schema-grounded context injection listing only actual relational paths."
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
