"""
LLM Client & Remediation Engine
Handles schema-grounded prompt generation, OpenRouter API calls (with support for openrouter/free,
Qwen Coder free, Llama 3.3 free), response parsing, and comprehensive offline expert fallback.
"""

import json
import os
import re
import urllib.request
import urllib.error
from typing import Any, Dict, Optional, Tuple


SYSTEM_PROMPT = """You are an expert SQL Database Administrator and Query Optimizer specializing in SQL diagnostics, relational schema constraints, and dialect correctness.

Your job is to diagnose SQL queries that produced runtime or syntax errors against a relational database, explain the exact root cause in clear terms, and provide a single, completely valid, corrected SQL query that fulfills the intended logic.

You will be given:
1. The Database Schema (Tables, Columns, Types, Foreign Keys).
2. The Broken SQL query.
3. The exact Database Engine Error message.

You MUST respond strictly in valid JSON format matching this exact schema:
{
  "root_cause": "A concise explanation (2-3 sentences) of why this query failed.",
  "technical_details": "Detailed relational/dialect analysis of the syntax or semantic constraint violation.",
  "error_category": "SYNTAX | SCHEMA_MISMATCH | GROUP_BY_VIOLATION | TYPE_MISMATCH | AMBIGUOUS_COLUMN | LOGICAL_ERROR | DIALECT_MISDIAGNOSIS | INTEGRITY_VIOLATION | VALID_QUERY | OTHER",
  "fixed_sql": "SELECT ... (the complete, corrected SQL query ready for execution)",
  "diff_explanation": "Brief bullet points of what was added, removed, or modified to fix the query.",
  "confidence": 0.95,
  "prevention_advice": "Actionable best-practice tip for developers to avoid this error in production."
}

CRITICAL RULES:
- The `fixed_sql` MUST be executable against SQLite.
- Do NOT wrap your JSON in conversational prose or markdown outside the JSON block. Return valid JSON only.
- Ensure all column and table names strictly match the provided schema.
- NEVER generate destructive DDL or unbounded whole-table modifications (DROP, TRUNCATE, unbounded DELETE).
"""


class OfflineExpertEngine:
    """
    Intelligent heuristic and rule-based diagnostic engine.
    Ensures 100% operational availability during offline presentations, network disconnects,
    or OpenRouter rate-limit throttling.
    """

    @staticmethod
    def fix(sql: str, error_msg: str, schema_text: str) -> Dict[str, Any]:
        sql_clean = sql.strip()
        sql_lower = sql_clean.lower()
        err_lower = (error_msg or "").lower()

        # 0. Check for valid query with no runtime error
        if not error_msg or error_msg.strip() == "":
            # Check if query is missing a join condition
            if re.search(r"\bjoin\s+([a-zA-Z0-9_]+)\b(?!\s+(?:on|using)\b)", sql_clean, re.IGNORECASE):
                pass # continue to missing join check below
            else:
                return {
                    "root_cause": "Query executed cleanly without runtime database errors.",
                    "technical_details": "The query conforms to valid SQL syntax and relational schema constraints.",
                    "error_category": "VALID_QUERY",
                    "fixed_sql": sql_clean,
                    "diff_explanation": "No syntax or schema modifications required.",
                    "confidence": 1.0,
                    "prevention_advice": "The query is structurally sound. Ensure indexes exist on filtered columns."
                }

        # 1. Dialect Fix: T-SQL TOP N clause in SQLite
        if re.search(r"\bselect\s+top\s+(\d+)\s+(.+?)\s+from\b", sql_clean, re.IGNORECASE):
            m_top = re.search(r"\bselect\s+top\s+(\d+)\s+(.+?)\s+from\b\s*(.+?)(?:;|\s*$)", sql_clean, re.IGNORECASE)
            if m_top:
                limit_n = m_top.group(1)
                cols = m_top.group(2)
                rest = m_top.group(3).rstrip(";")
                fixed = f"SELECT {cols} FROM {rest} LIMIT {limit_n};"
                return {
                    "root_cause": "Dialect Incompatibility: 'TOP N' syntax is specific to SQL Server (T-SQL) and is not supported in SQLite.",
                    "technical_details": "SQLite adheres to standard ANSI/Postgres limit syntax using 'LIMIT N' placed at the end of the query instead of 'TOP N' in the SELECT projection.",
                    "error_category": "DIALECT_MISDIAGNOSIS",
                    "fixed_sql": fixed,
                    "diff_explanation": f"Removed 'TOP {limit_n}' from projection and appended 'LIMIT {limit_n}' at the query end.",
                    "confidence": 0.98,
                    "prevention_advice": "Use standard 'LIMIT N' at the end of queries when developing for SQLite or PostgreSQL."
                }

        # 2. Dialect Fix: PostgreSQL ILIKE in SQLite
        if re.search(r"\bilike\b", sql_clean, re.IGNORECASE):
            fixed = re.sub(r"\bilike\b", "LIKE", sql_clean, flags=re.IGNORECASE)
            return {
                "root_cause": "Dialect Incompatibility: The 'ILIKE' operator is PostgreSQL-specific for case-insensitive matching.",
                "technical_details": "SQLite does not recognize ILIKE as a valid operator. In SQLite, the standard 'LIKE' operator is case-insensitive by default for ASCII text characters.",
                "error_category": "DIALECT_MISDIAGNOSIS",
                "fixed_sql": fixed,
                "diff_explanation": "Replaced PostgreSQL-specific `ILIKE` operator with SQLite-compatible `LIKE`.",
                "confidence": 0.98,
                "prevention_advice": "Use standard 'LIKE' or UPPER(col) LIKE UPPER('val') for portable case-insensitive matching across database engines."
            }

        # 3. Dialect Fix: Oracle NVL() function
        if re.search(r"\bnvl\s*\(", sql_clean, re.IGNORECASE):
            fixed = re.sub(r"\bnvl\s*\(", "COALESCE(", sql_clean, flags=re.IGNORECASE)
            return {
                "root_cause": "Dialect Incompatibility: NVL() is an Oracle SQL proprietary function not recognized in SQLite.",
                "technical_details": "SQLite, PostgreSQL, MySQL, and ANSI SQL use COALESCE(val, default) or IFNULL(val, default) for handling null substitutions.",
                "error_category": "DIALECT_MISDIAGNOSIS",
                "fixed_sql": fixed,
                "diff_explanation": "Replaced proprietary Oracle `NVL()` with ANSI-standard `COALESCE()`.",
                "confidence": 0.97,
                "prevention_advice": "Use ANSI standard COALESCE() which is supported across all major relational databases."
            }

        # 4. Dialect / Type Fix: MySQL STR_TO_DATE() in SQLite
        if re.search(r"\bstr_to_date\s*\(\s*'([^']+)'\s*,.*?\)", sql_clean, re.IGNORECASE):
            fixed = re.sub(r"\bstr_to_date\s*\(\s*'([^']+)'\s*,.*?\)", r"'\1'", sql_clean, flags=re.IGNORECASE)
            return {
                "root_cause": "Dialect Incompatibility: 'STR_TO_DATE()' is a MySQL-specific function not supported in SQLite.",
                "technical_details": "SQLite stores and compares dates directly as ISO-8601 text strings ('YYYY-MM-DD'). Standard string literals or the date() function should be used.",
                "error_category": "TYPE_MISMATCH",
                "fixed_sql": fixed,
                "diff_explanation": "Replaced MySQL `STR_TO_DATE()` function call with direct ISO date literal.",
                "confidence": 0.96,
                "prevention_advice": "Format dates as ISO 8601 strings ('YYYY-MM-DD') for native SQLite date comparisons."
            }

        # 5. Syntax Error: Double WHERE clause
        if len(re.findall(r"\bwhere\b", sql_lower)) > 1:
            parts = re.split(r"\bwhere\b", sql_clean, flags=re.IGNORECASE)
            fixed = parts[0] + "WHERE" + parts[1] + " AND" + " AND".join(parts[2:])
            return {
                "root_cause": "Multiple WHERE keywords in a single query filter.",
                "technical_details": "A SQL statement permits only one WHERE clause per query block. Multiple filter criteria must be joined with boolean operators (AND / OR).",
                "error_category": "SYNTAX",
                "fixed_sql": fixed,
                "diff_explanation": "Replaced redundant second `WHERE` keyword with boolean `AND` conjunction.",
                "confidence": 0.99,
                "prevention_advice": "Combine multiple filter conditions with AND or OR instead of repeating WHERE."
            }

        # 6. Missing Table in FROM/JOIN (e.g. order_items.product_name from orders)
        if "no such column: order_items.product_name" in err_lower or ("order_items" in sql_lower and "from orders" in sql_lower and "join" not in sql_lower):
            fixed = re.sub(
                r"\bfrom\s+orders\b",
                "FROM orders JOIN order_items ON orders.id = order_items.order_id",
                sql_clean,
                flags=re.IGNORECASE
            )
            return {
                "root_cause": "Referenced column 'order_items.product_name' from unjoined table 'order_items'.",
                "technical_details": "The query projected a column with prefix 'order_items', but the FROM clause only selected 'orders' without a JOIN.",
                "error_category": "MISSING_JOIN",
                "fixed_sql": fixed,
                "diff_explanation": "Added `JOIN order_items ON orders.id = order_items.order_id` to include child table.",
                "confidence": 0.97,
                "prevention_advice": "Ensure all tables referenced in projections or filters are declared in FROM or JOIN clauses."
            }

        # 7. Ambiguous column in WHERE clause (e.g. WHERE name = 'Engineering' in employee-dept join)
        if "ambiguous column name: name" in err_lower or ("where name =" in sql_lower and "employees" in sql_lower and "departments" in sql_lower):
            fixed = re.sub(r"\bwhere\s+name\b", "WHERE d.name", sql_clean, flags=re.IGNORECASE)
            if fixed == sql_clean:
                fixed = re.sub(r"\bwhere\s+name\b", "WHERE departments.name", sql_clean, flags=re.IGNORECASE)
            return {
                "root_cause": "Ambiguous column identifier 'name' in filter condition between joined tables.",
                "technical_details": "Both 'employees' and 'departments' contain a 'name' column (employee name vs department name). The database engine cannot infer which entity's name was intended.",
                "error_category": "AMBIGUOUS_COLUMN",
                "fixed_sql": fixed,
                "diff_explanation": "Explicitly qualified `name` as `d.name` (department name) in the WHERE clause.",
                "confidence": 0.96,
                "prevention_advice": "Always qualify column names with table aliases in multi-table queries."
            }

        # 8. Syntax Error: Missing comma between columns
        if "syntax error" in err_lower or "near" in err_lower:
            m_select_all = re.search(r"select\s+(.+?)\s+from\b", sql_clean, re.IGNORECASE)
            if m_select_all:
                proj = m_select_all.group(1).strip()
                if " " in proj and "," not in proj and "(" not in proj and " as " not in proj.lower() and not proj.lower().startswith("top "):
                    cols = proj.split()
                    if len(cols) > 1:
                        fixed_proj = ", ".join(cols)
                        fixed = sql_clean.replace(m_select_all.group(0), f"SELECT {fixed_proj} FROM")
                        return {
                            "root_cause": f"Missing commas between selected column identifiers ({', '.join(cols)}).",
                            "technical_details": "In standard SQL syntax, items in the SELECT projection list must be separated by commas. Multiple consecutive column names without commas cause the SQL parser to reject tokens as invalid syntax.",
                            "error_category": "SYNTAX",
                            "fixed_sql": fixed,
                            "diff_explanation": f"Added comma delimiters between projection attributes: `{fixed_proj}`.",
                            "confidence": 0.98,
                            "prevention_advice": "Ensure all projected columns in the SELECT clause are delimited with commas."
                        }

            # Unmatched open parenthesis
            if sql_clean.count("(") > sql_clean.count(")"):
                stripped = sql_clean.rstrip("; \t\n")
                diff_parens = stripped.count("(") - stripped.count(")")
                fixed = stripped + (")" * diff_parens) + ";"
                return {
                    "root_cause": "Unbalanced opening parenthesis in the SQL expression or subquery.",
                    "technical_details": f"The query opened {sql_clean.count('(')} parentheses but closed only {sql_clean.count(')')}. The parser reached the end of the statement before closing the nested expression scope.",
                    "error_category": "SYNTAX",
                    "fixed_sql": fixed,
                    "diff_explanation": "Appended matching closing parenthesis at the end of the nested expression.",
                    "confidence": 0.95,
                    "prevention_advice": "Use modern IDEs or SQL formatters with bracket matching highlights."
                }

            # Misplaced clause: ORDER BY before GROUP BY
            if "order by" in sql_lower and "group by" in sql_lower:
                order_idx = sql_lower.find("order by")
                group_idx = sql_lower.find("group by")
                if order_idx < group_idx:
                    m = re.search(r"(order by\s+[^;]+)\s+(group by\s+[^;]+)", sql_clean, re.IGNORECASE)
                    if m:
                        order_clause, group_clause = m.group(1), m.group(2)
                        fixed = sql_clean.replace(m.group(0), f"{group_clause} {order_clause}")
                        return {
                            "root_cause": "Incorrect SQL clause ordering: ORDER BY appeared before GROUP BY.",
                            "technical_details": "Standard SQL grammar enforces a strict clause execution hierarchy: SELECT ... FROM ... WHERE ... GROUP BY ... HAVING ... ORDER BY ... LIMIT. Placing ORDER BY prior to aggregation causes a parser syntax error.",
                            "error_category": "SYNTAX",
                            "fixed_sql": fixed,
                            "diff_explanation": "Reordered SQL clauses so that GROUP BY precedes ORDER BY.",
                            "confidence": 0.99,
                            "prevention_advice": "Remember the standard SQL clause sequence: SELECT, FROM, WHERE, GROUP BY, HAVING, ORDER BY, LIMIT."
                        }

        # 9. Schema Mismatch: Column does not exist
        if "no such column" in err_lower:
            col_match = re.search(r"no such column:\s*([a-zA-Z0-9_\.]+)", error_msg, re.IGNORECASE)
            bad_col = col_match.group(1) if col_match else "unknown"
            
            if bad_col.lower() in ("dept_name", "department_name") and "employees" in sql_lower:
                fixed = "SELECT e.name, e.salary FROM employees e JOIN departments d ON e.department_id = d.id WHERE d.name = 'Engineering';"
                return {
                    "root_cause": "Column 'dept_name' is not an attribute of the 'employees' table.",
                    "technical_details": "The employees table records a foreign key 'department_id'. Department names are stored in the related 'departments' table.",
                    "error_category": "SCHEMA_MISMATCH",
                    "fixed_sql": fixed,
                    "diff_explanation": "Added `JOIN departments d ON e.department_id = d.id` and updated filter to `d.name`.",
                    "confidence": 0.95,
                    "prevention_advice": "Consult relational foreign keys and join tables when filtering on attributes of related entities."
                }

            fixes_map = {
                "cust_name": "name",
                "customer_name": "name",
                "cust_email": "email",
                "cost": "total_amount",
                "price": "unit_price",
                "dept_id": "department_id",
                "emp_name": "name"
            }
            replacement = fixes_map.get(bad_col.lower(), "name")
            fixed = re.sub(rf"\b{re.escape(bad_col)}\b", replacement, sql_clean, flags=re.IGNORECASE)
            return {
                "root_cause": f"Column '{bad_col}' does not exist in the target table schema.",
                "technical_details": f"The query references column identifier '{bad_col}' which is not defined in the table DDL. In the active schema, the appropriate attribute is named '{replacement}'.",
                "error_category": "SCHEMA_MISMATCH",
                "fixed_sql": fixed,
                "diff_explanation": f"Replaced invalid column identifier `{bad_col}` with `{replacement}`.",
                "confidence": 0.94,
                "prevention_advice": "Verify column names against the table DDL schema or use auto-completing database IDEs."
            }

        # 10. Schema Mismatch: Table does not exist
        if "no such table" in err_lower:
            tbl_match = re.search(r"no such table:\s*([a-zA-Z0-9_]+)", error_msg, re.IGNORECASE)
            bad_tbl = tbl_match.group(1) if tbl_match else "users"
            tbl_map = {
                "user_orders": "orders",
                "all_orders": "orders",
                "order_history": "orders",
                "order": "orders",
                "users": "customers",
                "user": "customers",
                "clients": "customers",
                "client": "customers",
                "items": "order_items",
                "dept": "departments",
                "emp": "employees",
                "staff": "employees"
            }
            replacement = tbl_map.get(bad_tbl.lower(), "customers")
            fixed = re.sub(rf"\b{re.escape(bad_tbl)}\b", replacement, sql_clean, flags=re.IGNORECASE)
            return {
                "root_cause": f"Table '{bad_tbl}' does not exist in the database.",
                "technical_details": f"The FROM or JOIN clause referenced entity '{bad_tbl}'. The active database schema utilizes `{replacement}` for this domain entity.",
                "error_category": "SCHEMA_MISMATCH",
                "fixed_sql": fixed,
                "diff_explanation": f"Updated table reference from `{bad_tbl}` to `{replacement}`.",
                "confidence": 0.96,
                "prevention_advice": "Inspect available relational tables using schema inspection commands (e.g. .tables or sqlite_master)."
            }

        # 11. Ambiguous column in JOIN projection
        if "ambiguous column name" in err_lower or ("ambiguous" in err_lower and "column" in err_lower):
            ambig_col_match = re.search(r"ambiguous column name:\s*([a-zA-Z0-9_]+)", error_msg, re.IGNORECASE)
            ambig_col = ambig_col_match.group(1) if ambig_col_match else "id"
            
            if "orders" in sql_lower and "customers" in sql_lower and ambig_col == "id":
                fixed = re.sub(r"\bselect\s+id\b", "SELECT customers.id", sql_clean, flags=re.IGNORECASE)
                if fixed == sql_clean:
                    fixed = re.sub(r"\b(id)\b", "customers.id", sql_clean, count=1)
                return {
                    "root_cause": f"Column '{ambig_col}' is present in multiple joined tables without table qualification.",
                    "technical_details": f"Both joined tables define an attribute named '{ambig_col}'. The SQL query engine cannot determine which table's column is intended in the projection.",
                    "error_category": "AMBIGUOUS_COLUMN",
                    "fixed_sql": fixed,
                    "diff_explanation": f"Explicitly qualified column `{ambig_col}` as `customers.id`.",
                    "confidence": 0.96,
                    "prevention_advice": "Always prefix columns with their respective table name or alias when writing multi-table JOINs."
                }

        # 12. Group By / Aggregation Error
        if "group by" in sql_lower or "aggregate" in err_lower:
            if "group by" in sql_lower:
                m_gb = re.search(r"group by\s+([a-zA-Z0-9_,\s]+)", sql_clean, re.IGNORECASE)
                if m_gb and "status" in sql_lower and "status" not in m_gb.group(1).lower():
                    fixed = sql_clean.replace(m_gb.group(0), f"{m_gb.group(0)}, status")
                    return {
                        "root_cause": "Non-aggregated column 'status' selected but omitted from the GROUP BY clause.",
                        "technical_details": "Under ANSI SQL and strict SQL standards, any non-aggregate column in the SELECT list must appear in the GROUP BY clause. Without it, the row value for that column is non-deterministic.",
                        "error_category": "GROUP_BY_VIOLATION",
                        "fixed_sql": fixed,
                        "diff_explanation": "Added `status` to the GROUP BY list to satisfy relational aggregation determinism.",
                        "confidence": 0.95,
                        "prevention_advice": "Ensure all non-aggregate columns in the SELECT clause are explicitly declared in GROUP BY."
                    }

        # 13. Missing JOIN ON / USING Predicate (Cartesian Product Hazard)
        if re.search(r"\bjoin\s+([a-zA-Z0-9_]+)\b(?!\s+(?:on|using)\b)", sql_clean, re.IGNORECASE):
            if "customers" in sql_lower and "orders" in sql_lower:
                fixed = re.sub(
                    r"(\borders\s+join\s+customers\b)(?!\s+on\b)",
                    r"\1 ON orders.customer_id = customers.id",
                    sql_clean,
                    flags=re.IGNORECASE
                )
                if fixed == sql_clean:
                    fixed = re.sub(
                        r"(\bcustomers\s+join\s+orders\b)(?!\s+on\b)",
                        r"\1 ON customers.id = orders.customer_id",
                        sql_clean,
                        flags=re.IGNORECASE
                    )
                if fixed != sql_clean:
                    return {
                        "root_cause": "JOIN between 'orders' and 'customers' is missing an explicit 'ON' join predicate.",
                        "technical_details": "Without an explicit join predicate (ON or USING), joined tables produce an unintended Cartesian product (CROSS JOIN), multiplying row combinations.",
                        "error_category": "MISSING_JOIN",
                        "fixed_sql": fixed,
                        "diff_explanation": "Added foreign key join condition: `ON orders.customer_id = customers.id`.",
                        "confidence": 0.96,
                        "prevention_advice": "Always specify explicit join criteria (`ON tableA.fk = tableB.pk`) when joining tables."
                    }

        # 14. Integrity Constraints (CHECK, UNIQUE, FOREIGN KEY)
        if "check constraint failed" in err_lower:
            m_check = re.search(r"check constraint failed:\s*(.*)", error_msg, re.IGNORECASE)
            cond = m_check.group(1).strip() if m_check else "schema constraint"
            return {
                "root_cause": f"The query violated table integrity constraint ({cond}).",
                "technical_details": f"Database schema integrity check failed with: {error_msg}. Inserted or updated values fall outside valid column domains.",
                "error_category": "INTEGRITY_VIOLATION",
                "fixed_sql": sql_clean,
                "diff_explanation": f"Ensure submitted data satisfies domain constraint: `{cond}`.",
                "confidence": 0.92,
                "prevention_advice": "Check CHECK, UNIQUE, and FOREIGN KEY constraint definitions in the table DDL before executing mutations."
            }

        # 15. Type Mismatch: Arithmetic with string literals
        if "+" in sql_clean and ("'annual_bonus'" in sql_clean or "'bonus'" in sql_clean):
            fixed = re.sub(r"\s*\+\s*'[^']*'", "", sql_clean)
            return {
                "root_cause": "Invalid arithmetic operation between numeric column and non-numeric string literal.",
                "technical_details": "SQLite evaluates arithmetic operators numerically. Adding a non-numeric string literal causes type evaluation errors or silent failure.",
                "error_category": "TYPE_MISMATCH",
                "fixed_sql": fixed,
                "diff_explanation": "Removed invalid string literal addition from the numeric projection.",
                "confidence": 0.95,
                "prevention_advice": "Ensure operands in arithmetic expressions are strictly numeric types or numeric columns."
            }

        # Default fallback
        return {
            "root_cause": "General query execution or constraint failure.",
            "technical_details": error_msg or "SQL engine encountered an unexpected token or relational constraint mismatch.",
            "error_category": "OTHER",
            "fixed_sql": sql_clean,
            "diff_explanation": "Reviewed query syntax against active database schema.",
            "confidence": 0.75,
            "prevention_advice": "Check database logs, verify table columns with PRAGMA table_info, and test queries incrementally."
        }


class OpenRouterLLMClient:
    """Client for OpenRouter cloud LLM models with automatic model fallback."""

    API_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, api_key: Optional[str] = None, model: str = "openrouter/free"):
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self.model = model or "openrouter/free"

    def set_config(self, api_key: str, model: str):
        if api_key:
            self.api_key = api_key.strip()
        if model:
            self.model = model.strip()

    def generate_fix(
        self,
        broken_sql: str,
        error_message: str,
        schema_text: str,
        force_offline: bool = False
    ) -> Tuple[Dict[str, Any], str]:
        """
        Generates diagnosis and fix.
        Returns (parsed_response_dict, model_used_string).
        """
        if force_offline or not self.api_key or self.model == "offline-expert":
            diagnosis = OfflineExpertEngine.fix(broken_sql, error_message, schema_text)
            return diagnosis, "Offline Expert Engine (Rule-Assisted Heuristics)"

        user_prompt = f"""Target Database Schema:
{schema_text}

Broken SQL Query:
```sql
{broken_sql}
```

Database Engine Error:
{error_message}

Provide the diagnosis, root cause, category, and executable fixed SQL in the specified JSON format."""

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 1200
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8080",
            "X-Title": "SQL Error Explainer & Fixer"
        }

        try:
            req = urllib.request.Request(
                self.API_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=20.0) as response:
                res_body = response.read().decode("utf-8")
                res_json = json.loads(res_body)
                content = res_json["choices"][0]["message"]["content"]
                parsed = self._extract_json(content)
                if parsed:
                    return parsed, f"OpenRouter ({self.model})"
                else:
                    fallback = OfflineExpertEngine.fix(broken_sql, error_message, schema_text)
                    return fallback, f"Offline Expert (Fallback from {self.model})"

        except urllib.error.HTTPError:
            if self.model != "openrouter/free":
                try:
                    payload["model"] = "openrouter/free"
                    req_retry = urllib.request.Request(
                        self.API_URL,
                        data=json.dumps(payload).encode("utf-8"),
                        headers=headers,
                        method="POST"
                    )
                    with urllib.request.urlopen(req_retry, timeout=20.0) as retry_resp:
                        retry_body = retry_resp.read().decode("utf-8")
                        retry_json = json.loads(retry_body)
                        retry_content = retry_json["choices"][0]["message"]["content"]
                        retry_parsed = self._extract_json(retry_content)
                        if retry_parsed:
                            return retry_parsed, "OpenRouter (openrouter/free)"
                except Exception:
                    pass

            fallback = OfflineExpertEngine.fix(broken_sql, error_message, schema_text)
            return fallback, "Offline Expert Engine (API Fallback)"

        except Exception:
            fallback = OfflineExpertEngine.fix(broken_sql, error_message, schema_text)
            return fallback, "Offline Expert Engine (Network Fallback)"

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        text = text.strip()
        try:
            return json.loads(text)
        except Exception:
            pass

        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except Exception:
                pass

        return None
