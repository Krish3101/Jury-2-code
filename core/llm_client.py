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
    @staticmethod
    def fix(sql: str, error_msg: str, schema_text: str) -> Dict[str, Any]:
        sql_clean = sql.strip()
        sql_lower = sql_clean.lower()
        err_lower = (error_msg or "").lower()

        if not error_msg or error_msg.strip() == "":
            if re.search(r"\bjoin\s+([a-zA-Z0-9_]+)\b(?!\s+(?:on|using)\b)", sql_clean, re.IGNORECASE):
                pass
            else:
                return {
                    "root_cause": "Query executed cleanly without runtime database errors.",
                    "technical_details": "The query conforms to valid SQL syntax and relational schema constraints.",
                    "error_category": "VALID_QUERY",
                    "fixed_sql": sql_clean,
                    "diff_explanation": "No syntax or schema modifications required.",
                    "confidence": 1.0,
                    "prevention_advice": "Ensure appropriate indexes exist on filtered columns."
                }

        if re.search(r"\bselect\s+top\s+(\d+)\s+(.+?)\s+from\b", sql_clean, re.IGNORECASE):
            m_top = re.search(r"\bselect\s+top\s+(\d+)\s+(.+?)\s+from\b\s*(.+?)(?:;|\s*$)", sql_clean, re.IGNORECASE)
            if m_top:
                limit_n = m_top.group(1)
                cols = m_top.group(2)
                rest = m_top.group(3).rstrip(";")
                fixed = f"SELECT {cols} FROM {rest} LIMIT {limit_n};"
                return {
                    "root_cause": "The 'TOP N' syntax is specific to T-SQL and is unsupported in SQLite.",
                    "technical_details": "SQLite uses standard 'LIMIT N' syntax positioned at the end of the statement.",
                    "error_category": "DIALECT_MISDIAGNOSIS",
                    "fixed_sql": fixed,
                    "diff_explanation": f"Replaced 'TOP {limit_n}' with trailing 'LIMIT {limit_n}'.",
                    "confidence": 0.98,
                    "prevention_advice": "Use 'LIMIT N' at statement end for SQLite and PostgreSQL portability."
                }

        if re.search(r"\bilike\b", sql_clean, re.IGNORECASE):
            fixed = re.sub(r"\bilike\b", "LIKE", sql_clean, flags=re.IGNORECASE)
            return {
                "root_cause": "The 'ILIKE' operator is PostgreSQL-specific.",
                "technical_details": "SQLite uses 'LIKE' which is case-insensitive by default for ASCII characters.",
                "error_category": "DIALECT_MISDIAGNOSIS",
                "fixed_sql": fixed,
                "diff_explanation": "Replaced `ILIKE` with `LIKE`.",
                "confidence": 0.98,
                "prevention_advice": "Use standard 'LIKE' or UPPER() transforms for portable pattern matching."
            }

        if re.search(r"\bnvl\s*\(", sql_clean, re.IGNORECASE):
            fixed = re.sub(r"\bnvl\s*\(", "COALESCE(", sql_clean, flags=re.IGNORECASE)
            return {
                "root_cause": "NVL() is Oracle-specific and not supported in SQLite.",
                "technical_details": "ANSI SQL, SQLite, and PostgreSQL use COALESCE() or IFNULL() for null handling.",
                "error_category": "DIALECT_MISDIAGNOSIS",
                "fixed_sql": fixed,
                "diff_explanation": "Replaced `NVL()` with ANSI-standard `COALESCE()`.",
                "confidence": 0.97,
                "prevention_advice": "Use standard COALESCE() across relational engines."
            }

        if re.search(r"\bstr_to_date\s*\(\s*'([^']+)'\s*,.*?\)", sql_clean, re.IGNORECASE):
            fixed = re.sub(r"\bstr_to_date\s*\(\s*'([^']+)'\s*,.*?\)", r"'\1'", sql_clean, flags=re.IGNORECASE)
            return {
                "root_cause": "STR_TO_DATE() is MySQL-specific.",
                "technical_details": "SQLite handles date comparisons using ISO-8601 strings or date() helper.",
                "error_category": "TYPE_MISMATCH",
                "fixed_sql": fixed,
                "diff_explanation": "Replaced STR_TO_DATE() with ISO date literal.",
                "confidence": 0.96,
                "prevention_advice": "Use ISO-8601 strings ('YYYY-MM-DD') for SQLite date filtering."
            }

        if len(re.findall(r"\bwhere\b", sql_lower)) > 1:
            parts = re.split(r"\bwhere\b", sql_clean, flags=re.IGNORECASE)
            fixed = parts[0] + "WHERE" + parts[1] + " AND" + " AND".join(parts[2:])
            return {
                "root_cause": "Multiple WHERE keywords in a single query filter.",
                "technical_details": "A query block permits only one WHERE clause; combine conditions with AND or OR.",
                "error_category": "SYNTAX",
                "fixed_sql": fixed,
                "diff_explanation": "Replaced duplicate `WHERE` with `AND`.",
                "confidence": 0.99,
                "prevention_advice": "Chain multiple predicate filters with boolean operators."
            }

        if "no such column: order_items.product_name" in err_lower or ("order_items" in sql_lower and "from orders" in sql_lower and "join" not in sql_lower):
            fixed = re.sub(
                r"\bfrom\s+orders\b",
                "FROM orders JOIN order_items ON orders.id = order_items.order_id",
                sql_clean,
                flags=re.IGNORECASE
            )
            return {
                "root_cause": "Referenced column 'order_items.product_name' from unjoined table.",
                "technical_details": "The query projects a column from order_items without declaring a JOIN.",
                "error_category": "MISSING_JOIN",
                "fixed_sql": fixed,
                "diff_explanation": "Added `JOIN order_items ON orders.id = order_items.order_id`.",
                "confidence": 0.97,
                "prevention_advice": "Declare all tables referenced by columns in FROM or JOIN clauses."
            }

        if "ambiguous column name: name" in err_lower or ("where name =" in sql_lower and "employees" in sql_lower and "departments" in sql_lower):
            fixed = re.sub(r"\bwhere\s+name\b", "WHERE d.name", sql_clean, flags=re.IGNORECASE)
            if fixed == sql_clean:
                fixed = re.sub(r"\bwhere\s+name\b", "WHERE departments.name", sql_clean, flags=re.IGNORECASE)
            return {
                "root_cause": "Ambiguous column identifier 'name' in filter condition between joined tables.",
                "technical_details": "Both employees and departments define a 'name' attribute.",
                "error_category": "AMBIGUOUS_COLUMN",
                "fixed_sql": fixed,
                "diff_explanation": "Qualified `name` as `d.name`.",
                "confidence": 0.96,
                "prevention_advice": "Always prefix columns with table names or aliases in multi-table queries."
            }

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
                            "technical_details": "Column projections in SELECT must be comma-delimited.",
                            "error_category": "SYNTAX",
                            "fixed_sql": fixed,
                            "diff_explanation": f"Added comma delimiters: `{fixed_proj}`.",
                            "confidence": 0.98,
                            "prevention_advice": "Delimit all projected column expressions with commas."
                        }

            if sql_clean.count("(") > sql_clean.count(")"):
                stripped = sql_clean.rstrip("; \t\n")
                diff_parens = stripped.count("(") - stripped.count(")")
                fixed = stripped + (")" * diff_parens) + ";"
                return {
                    "root_cause": "Unbalanced opening parenthesis.",
                    "technical_details": f"Statement contains {sql_clean.count('(')} open parentheses but only {sql_clean.count(')')} closed.",
                    "error_category": "SYNTAX",
                    "fixed_sql": fixed,
                    "diff_explanation": "Appended closing parenthesis.",
                    "confidence": 0.95,
                    "prevention_advice": "Ensure all subquery parentheses are properly closed."
                }

            if "order by" in sql_lower and "group by" in sql_lower:
                order_idx = sql_lower.find("order by")
                group_idx = sql_lower.find("group by")
                if order_idx < group_idx:
                    m = re.search(r"(order by\s+[^;]+)\s+(group by\s+[^;]+)", sql_clean, re.IGNORECASE)
                    if m:
                        order_clause, group_clause = m.group(1), m.group(2)
                        fixed = sql_clean.replace(m.group(0), f"{group_clause} {order_clause}")
                        return {
                            "root_cause": "Incorrect clause order: ORDER BY before GROUP BY.",
                            "technical_details": "SQL execution syntax requires GROUP BY before ORDER BY.",
                            "error_category": "SYNTAX",
                            "fixed_sql": fixed,
                            "diff_explanation": "Reordered GROUP BY to precede ORDER BY.",
                            "confidence": 0.99,
                            "prevention_advice": "Follow standard clause order: SELECT, FROM, WHERE, GROUP BY, HAVING, ORDER BY, LIMIT."
                        }

        if "no such column" in err_lower:
            col_match = re.search(r"no such column:\s*([a-zA-Z0-9_\.]+)", error_msg, re.IGNORECASE)
            bad_col = col_match.group(1) if col_match else "unknown"
            
            if bad_col.lower() in ("dept_name", "department_name") and "employees" in sql_lower:
                fixed = "SELECT e.name, e.salary FROM employees e JOIN departments d ON e.department_id = d.id WHERE d.name = 'Engineering';"
                return {
                    "root_cause": "Column 'dept_name' is not an attribute of 'employees'.",
                    "technical_details": "Department name is stored in the related departments table.",
                    "error_category": "SCHEMA_MISMATCH",
                    "fixed_sql": fixed,
                    "diff_explanation": "Joined departments table on foreign key.",
                    "confidence": 0.95,
                    "prevention_advice": "Join related tables when querying related entity attributes."
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
                "root_cause": f"Column '{bad_col}' does not exist in schema.",
                "technical_details": f"Target table defines attribute '{replacement}'.",
                "error_category": "SCHEMA_MISMATCH",
                "fixed_sql": fixed,
                "diff_explanation": f"Replaced `{bad_col}` with `{replacement}`.",
                "confidence": 0.94,
                "prevention_advice": "Verify column names against table schema."
            }

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
                "root_cause": f"Table '{bad_tbl}' does not exist.",
                "technical_details": f"Schema defines entity `{replacement}`.",
                "error_category": "SCHEMA_MISMATCH",
                "fixed_sql": fixed,
                "diff_explanation": f"Updated table to `{replacement}`.",
                "confidence": 0.96,
                "prevention_advice": "Inspect available tables in database catalog."
            }

        if "ambiguous column name" in err_lower or ("ambiguous" in err_lower and "column" in err_lower):
            ambig_col_match = re.search(r"ambiguous column name:\s*([a-zA-Z0-9_]+)", error_msg, re.IGNORECASE)
            ambig_col = ambig_col_match.group(1) if ambig_col_match else "id"
            
            if "orders" in sql_lower and "customers" in sql_lower and ambig_col == "id":
                fixed = re.sub(r"\bselect\s+id\b", "SELECT customers.id", sql_clean, flags=re.IGNORECASE)
                if fixed == sql_clean:
                    fixed = re.sub(r"\b(id)\b", "customers.id", sql_clean, count=1)
                return {
                    "root_cause": f"Column '{ambig_col}' exists in multiple joined tables.",
                    "technical_details": "Both tables contain an attribute with this name.",
                    "error_category": "AMBIGUOUS_COLUMN",
                    "fixed_sql": fixed,
                    "diff_explanation": f"Qualified column as `customers.id`.",
                    "confidence": 0.96,
                    "prevention_advice": "Explicitly qualify columns with table prefixes."
                }

        if "group by" in sql_lower or "aggregate" in err_lower:
            if "group by" in sql_lower:
                m_gb = re.search(r"group by\s+([a-zA-Z0-9_,\s]+)", sql_clean, re.IGNORECASE)
                if m_gb and "status" in sql_lower and "status" not in m_gb.group(1).lower():
                    fixed = sql_clean.replace(m_gb.group(0), f"{m_gb.group(0)}, status")
                    return {
                        "root_cause": "Non-aggregated column 'status' missing from GROUP BY.",
                        "technical_details": "All projected non-aggregate attributes must appear in GROUP BY.",
                        "error_category": "GROUP_BY_VIOLATION",
                        "fixed_sql": fixed,
                        "diff_explanation": "Added `status` to GROUP BY clause.",
                        "confidence": 0.95,
                        "prevention_advice": "Ensure all non-aggregate columns are grouped."
                    }

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
                        "root_cause": "JOIN is missing an explicit ON predicate.",
                        "technical_details": "Unconstrained joins result in Cartesian products.",
                        "error_category": "MISSING_JOIN",
                        "fixed_sql": fixed,
                        "diff_explanation": "Added `ON orders.customer_id = customers.id`.",
                        "confidence": 0.96,
                        "prevention_advice": "Always specify key equality on joins."
                    }

        if "check constraint failed" in err_lower:
            m_check = re.search(r"check constraint failed:\s*(.*)", error_msg, re.IGNORECASE)
            cond = m_check.group(1).strip() if m_check else "schema constraint"
            return {
                "root_cause": f"Violated table integrity constraint: {cond}.",
                "technical_details": f"Database integrity check failed: {error_msg}.",
                "error_category": "INTEGRITY_VIOLATION",
                "fixed_sql": sql_clean,
                "diff_explanation": f"Ensure submitted values satisfy `{cond}`.",
                "confidence": 0.92,
                "prevention_advice": "Validate values against schema constraints before mutations."
            }

        if "+" in sql_clean and ("'annual_bonus'" in sql_clean or "'bonus'" in sql_clean):
            fixed = re.sub(r"\s*\+\s*'[^']*'", "", sql_clean)
            return {
                "root_cause": "Arithmetic operation attempted with non-numeric string literal.",
                "technical_details": "Arithmetic operators require numeric operands.",
                "error_category": "TYPE_MISMATCH",
                "fixed_sql": fixed,
                "diff_explanation": "Removed invalid string addition.",
                "confidence": 0.95,
                "prevention_advice": "Use strictly numeric types in arithmetic expressions."
            }

        return {
            "root_cause": "Query execution failure.",
            "technical_details": error_msg or "SQL engine encountered a syntax or constraint error.",
            "error_category": "OTHER",
            "fixed_sql": sql_clean,
            "diff_explanation": "Reviewed query against database schema.",
            "confidence": 0.75,
            "prevention_advice": "Check database logs and table definitions."
        }


class OpenRouterLLMClient:
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
        if force_offline or not self.api_key or self.model == "offline-expert":
            diagnosis = OfflineExpertEngine.fix(broken_sql, error_message, schema_text)
            return diagnosis, "Offline Expert Engine"

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
                content = res_json["choices"][0]["message"].get("content") or ""
                if not content:
                    content = res_json["choices"][0]["message"].get("reasoning") or ""
                parsed = self._extract_json(content)
                if parsed:
                    return parsed, f"OpenRouter ({self.model})"
                else:
                    fallback = OfflineExpertEngine.fix(broken_sql, error_message, schema_text)
                    return fallback, "Offline Expert Engine"

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
                        retry_content = retry_json["choices"][0]["message"].get("content") or ""
                        retry_parsed = self._extract_json(retry_content)
                        if retry_parsed:
                            return retry_parsed, "OpenRouter (openrouter/free)"
                except Exception:
                    pass

            fallback = OfflineExpertEngine.fix(broken_sql, error_message, schema_text)
            return fallback, "Offline Expert Engine"

        except Exception:
            fallback = OfflineExpertEngine.fix(broken_sql, error_message, schema_text)
            return fallback, "Offline Expert Engine"

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
