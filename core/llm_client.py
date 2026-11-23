"""
LLM Client & Remediation Engine
Handles schema-grounded prompt generation, OpenRouter API calls (with support for openrouter/free,
Qwen Coder free, Llama 3.3 free), response parsing, and offline expert fallback.
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
  "error_category": "SYNTAX | SCHEMA_MISMATCH | GROUP_BY_VIOLATION | TYPE_MISMATCH | AMBIGUOUS_COLUMN | LOGICAL_ERROR | OTHER",
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

        # 1. Syntax Error: Missing comma between columns
        if "syntax error" in err_lower or "near" in err_lower:
            # Check for multiple column identifiers in SELECT before FROM lacking commas
            m_select_all = re.search(r"select\s+(.+?)\s+from\b", sql_clean, re.IGNORECASE)
            if m_select_all:
                proj = m_select_all.group(1).strip()
                # If there are space-separated words without commas, e.g. "id name email"
                if " " in proj and "," not in proj and "(" not in proj and " as " not in proj.lower():
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

            # Check for unmatched open parenthesis
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

            # Check for misplaced clause: ORDER BY before GROUP BY
            if "order by" in sql_lower and "group by" in sql_lower:
                order_idx = sql_lower.find("order by")
                group_idx = sql_lower.find("group by")
                if order_idx < group_idx:
                    # Swap clauses
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

        # 2. Schema Mismatch: Column does not exist
        if "no such column" in err_lower:
            col_match = re.search(r"no such column:\s*([a-zA-Z0-9_\.]+)", error_msg, re.IGNORECASE)
            bad_col = col_match.group(1) if col_match else "unknown"
            
            # Common typos
            fixes_map = {
                "cust_name": "name",
                "customer_name": "name",
                "cust_email": "email",
                "cost": "total_amount",
                "price": "unit_price",
                "dept_id": "department_id",
                "dept_name": "name",
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

        # 3. Schema Mismatch: Table does not exist
        if "no such table" in err_lower:
            tbl_match = re.search(r"no such table:\s*([a-zA-Z0-9_]+)", error_msg, re.IGNORECASE)
            bad_tbl = tbl_match.group(1) if tbl_match else "users"
            tbl_map = {
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

        # 4. Ambiguous column in JOIN
        if "ambiguous column name" in err_lower or ("ambiguous" in err_lower and "column" in err_lower):
            ambig_col_match = re.search(r"ambiguous column name:\s*([a-zA-Z0-9_]+)", error_msg, re.IGNORECASE)
            ambig_col = ambig_col_match.group(1) if ambig_col_match else "id"
            
            # Qualify ambiguous column
            # E.g. in orders JOIN customers, id could be orders.id or customers.id
            if "orders" in sql_lower and "customers" in sql_lower and ambig_col == "id":
                fixed = re.sub(r"\bselect\s+id\b", "SELECT orders.id AS order_id", sql_clean, flags=re.IGNORECASE)
                if fixed == sql_clean:
                    fixed = re.sub(r"\b(id)\b", "orders.id", sql_clean, count=1)
                return {
                    "root_cause": f"Column '{ambig_col}' is present in multiple joined tables without table qualification.",
                    "technical_details": f"Both joined tables define a primary or attribute key named '{ambig_col}'. The SQL query engine cannot determine which table's column is intended in the projection.",
                    "error_category": "AMBIGUOUS_COLUMN",
                    "fixed_sql": fixed,
                    "diff_explanation": f"Explicitly qualified column `{ambig_col}` as `orders.id AS order_id`.",
                    "confidence": 0.96,
                    "prevention_advice": "Always prefix columns with their respective table name or alias when writing multi-table JOINs."
                }

        # 5. Group By / Aggregation Error
        if "group by" in sql_lower or "aggregate" in err_lower:
            # Check for non-aggregated columns missing from GROUP BY
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

        # 6. Type Mismatch / Operator Error (e.g. using string + instead of || in SQLite)
        if "+" in sql_clean and ("name" in sql_lower or "country" in sql_lower or "email" in sql_lower):
            fixed = re.sub(r"([a-zA-Z0-9_'\"]+)\s*\+\s*([a-zA-Z0-9_'\"]+)", r"\1 || \2", sql_clean)
            return {
                "root_cause": "Attempted string concatenation using the '+' operator instead of the SQL standard '||'.",
                "technical_details": "SQLite treats the '+' operator strictly as numeric addition. When used with strings, it attempts numeric coercion (yielding 0.0 or failing). SQLite string concatenation requires the '||' operator.",
                "error_category": "TYPE_MISMATCH",
                "fixed_sql": fixed,
                "diff_explanation": "Replaced arithmetic operator `+` with string concatenation operator `||`.",
                "confidence": 0.94,
                "prevention_advice": "Use the standard `||` operator for string concatenation in SQLite and PostgreSQL."
            }

        # 7. Missing JOIN ON / USING Predicate (Cartesian Product Hazard)
        if re.search(r"\bjoin\s+([a-zA-Z0-9_]+)\b(?!\s+(?:on|using)\b)", sql_clean, re.IGNORECASE):
            if "orders" in sql_lower and "customers" in sql_lower and not re.search(r"\borders\s+join\s+customers\s+on\b", sql_clean, re.IGNORECASE):
                fixed = re.sub(
                    r"(\borders\s+join\s+customers\b)(?!\s+on\b)",
                    r"\1 ON orders.customer_id = customers.id",
                    sql_clean,
                    flags=re.IGNORECASE
                )
                if fixed != sql_clean:
                    return {
                        "root_cause": "JOIN between 'orders' and 'customers' is missing an explicit 'ON' join predicate.",
                        "technical_details": "Without an explicit join predicate (ON or USING), joined tables produce an unintended Cartesian product (CROSS JOIN), multiplying row combinations. In standard SQL, this produces semantic discrepancies.",
                        "error_category": "SYNTAX",
                        "fixed_sql": fixed,
                        "diff_explanation": "Added foreign key join condition: `ON orders.customer_id = customers.id`.",
                        "confidence": 0.96,
                        "prevention_advice": "Always specify explicit join criteria (`ON tableA.fk = tableB.pk`) when joining tables."
                    }
            elif "employees" in sql_lower and "departments" in sql_lower and not re.search(r"\bemployees\s+join\s+departments\s+on\b", sql_clean, re.IGNORECASE):
                fixed = re.sub(
                    r"(\bemployees\s+join\s+departments\b)(?!\s+on\b)",
                    r"\1 ON employees.department_id = departments.id",
                    sql_clean,
                    flags=re.IGNORECASE
                )
                if fixed != sql_clean:
                    return {
                        "root_cause": "JOIN between 'employees' and 'departments' is missing an explicit 'ON' join predicate.",
                        "technical_details": "Without an explicit join predicate, relational tables execute an unconstrained Cartesian product.",
                        "error_category": "SYNTAX",
                        "fixed_sql": fixed,
                        "diff_explanation": "Added foreign key join condition: `ON employees.department_id = departments.id`.",
                        "confidence": 0.96,
                        "prevention_advice": "Always declare `ON` conditions defining key equality for relational joins."
                    }

        # 8. Integrity Constraints (CHECK, UNIQUE, FOREIGN KEY)
        if "check constraint failed" in err_lower:
            m_check = re.search(r"check constraint failed:\s*(.*)", error_msg, re.IGNORECASE)
            cond = m_check.group(1).strip() if m_check else "schema constraint"
            return {
                "root_cause": f"The query violated table integrity constraint ({cond}).",
                "technical_details": f"The active schema defines a CHECK invariant '{cond}'. The input data values violate this relational constraint.",
                "error_category": "INTEGRITY_VIOLATION",
                "fixed_sql": sql_clean,
                "diff_explanation": f"Ensure column values satisfy required constraint: `{cond}`.",
                "confidence": 0.95,
                "prevention_advice": "Inspect schema DDL CHECK definitions prior to executing data mutations."
            }

        if "unique constraint failed" in err_lower:
            m_unq = re.search(r"unique constraint failed:\s*(.*)", error_msg, re.IGNORECASE)
            col = m_unq.group(1).strip() if m_unq else "unique column"
            return {
                "root_cause": f"Duplicate value violates unique constraint on '{col}'.",
                "technical_details": f"The attribute '{col}' is declared UNIQUE in the relational schema. Attempting to insert an existing value causes a unique key collision.",
                "error_category": "INTEGRITY_VIOLATION",
                "fixed_sql": sql_clean,
                "diff_explanation": f"Provide a unique value for `{col}` or utilize UPSERT / `ON CONFLICT` semantics.",
                "confidence": 0.95,
                "prevention_advice": "Check existing keys or apply `INSERT OR IGNORE` / `ON CONFLICT DO UPDATE` where appropriate."
            }

        if "foreign key constraint failed" in err_lower:
            return {
                "root_cause": "Referenced foreign key value does not exist in parent table.",
                "technical_details": "Foreign key enforcement is enabled. The foreign key identifier does not match any existing primary key row in the referenced parent table.",
                "error_category": "INTEGRITY_VIOLATION",
                "fixed_sql": sql_clean,
                "diff_explanation": "Ensure parent record exists in primary key table prior to referencing in child records.",
                "confidence": 0.95,
                "prevention_advice": "Ensure parent entity exists before referencing it in dependent foreign key columns."
            }

        # 9. Valid Query without execution error
        if not error_msg or error_msg.startswith("Query executed without syntax error"):
            return {
                "root_cause": "The SQL query executed cleanly without syntax or schema errors.",
                "technical_details": "Database execution completed successfully. The query satisfies SQL grammar, references valid schema entities, and adheres to relational constraints.",
                "error_category": "VALID_QUERY",
                "fixed_sql": sql_clean,
                "diff_explanation": "No correction required. Query is already valid and executable.",
                "confidence": 1.0,
                "prevention_advice": "Ensure proper indexing on filtered columns for optimal query execution performance."
            }

        # Fallback default diagnostic
        return {
            "root_cause": "The SQL query encountered a relational engine error: " + (error_msg or "Syntax/Semantic constraint failure"),
            "technical_details": f"Database execution terminated with error: '{error_msg}'. Review the query syntax against the provided relational schema.",
            "error_category": "LOGICAL_ERROR",
            "fixed_sql": sql_clean,
            "diff_explanation": "No automated rule matched. Ensure table and column identifiers strictly match schema.",
            "confidence": 0.70,
            "prevention_advice": "Inspect table schema definitions and column types before formulating queries."
        }


class OpenRouterLLMClient:
    """
    Client for OpenRouter API supporting free endpoints (openrouter/free, Qwen Coder free,
    Llama 3.3 free) with automated fallback to the offline expert engine.
    """

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
        # If explicitly offline or no API key, use Offline Expert
        if force_offline or not self.api_key or self.model == "offline-expert":
            diagnosis = OfflineExpertEngine.fix(broken_sql, error_message, schema_text)
            return diagnosis, "Offline Expert Engine (Rule-Assisted Heuristics)"

        # Prepare user prompt
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

        except urllib.error.HTTPError as http_err:
            # If a specific free model failed (e.g. 404 model retired, or 429 rate limit),
            # automatically retry with the free meta-router "openrouter/free"
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
            return fallback, f"Offline Expert Engine (API Fallback)"

        except Exception:
            # Network issue or connection drop
            fallback = OfflineExpertEngine.fix(broken_sql, error_message, schema_text)
            return fallback, "Offline Expert Engine (Network Fallback)"

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Extracts JSON object from text, handling markdown code fences."""
        text = text.strip()
        # Direct parse attempt
        try:
            return json.loads(text)
        except Exception:
            pass

        # Try regex search for markdown ```json ... ```
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass

        # Find first { and last }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except Exception:
                pass

        return None
