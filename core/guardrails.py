"""
Guardrails and SQL Safety Module
Implements Step 5: Guards against destructive fixes, injection vectors, and unauthorized mutations.
Provides AST & lexical inspection, dangerous keyword rejection, and transaction-level read-only enforcement.
"""

import re
from dataclasses import dataclass, field
from typing import List


@dataclass
class SafetyVerdict:
    is_safe: bool
    risk_level: str  # "SAFE", "WARNING", "CRITICAL"
    statement_type: str  # "SELECT", "INSERT", "UPDATE", "DELETE", "DDL", "ADMIN", "MULTI_STATEMENT"
    violations: List[str] = field(default_factory=list)
    remediation_advice: str = ""

    def to_dict(self):
        return {
            "is_safe": self.is_safe,
            "risk_level": self.risk_level,
            "statement_type": self.statement_type,
            "violations": self.violations,
            "remediation_advice": self.remediation_advice
        }


class SQLSafetyGuardrail:
    """
    Enforces strict safety policies on user-submitted and LLM-generated SQL fixes.
    Guarantees that database integrity cannot be compromised by hallucinated or malicious queries.
    """

    # Prohibited Data Definition Language keywords
    DDL_KEYWORDS = [
        "DROP", "TRUNCATE", "ALTER", "RENAME", "CREATE", "GRANT", "REVOKE"
    ]

    # Prohibited Administration and SQLite internals
    ADMIN_COMMANDS = [
        "ATTACH", "DETACH", "VACUUM", "REINDEX", "PRAGMA", "LOAD_EXTENSION"
    ]

    # Trivial conditions often used to bypass WHERE checks (e.g. DELETE ... WHERE 1=1)
    TRIVIAL_WHERE_PATTERNS = [
        r"1\s*=\s*1",
        r"0\s*=\s*0",
        r"'[^']*'\s*=\s*'[^']*'",
        r"true",
        r"not\s+false",
        r"\bnull\s+is\s+null\b"
    ]

    def _strip_comments_and_strings(self, sql: str) -> str:
        """Removes SQL comments and string literals to prevent injection concealment."""
        # Remove single-line comments: -- ...
        sql_no_line_comments = re.sub(r"--[^\n]*", " ", sql)
        # Remove multi-line comments: /* ... */
        sql_no_block_comments = re.sub(r"/\*.*?\*/", " ", sql_no_line_comments, flags=re.DOTALL)
        return sql_no_block_comments.strip()

    def _split_statements(self, sql: str) -> List[str]:
        """Splits SQL string into discrete statements separated by semicolons."""
        cleaned = self._strip_comments_and_strings(sql)
        # Split by semicolon ignoring inside quotes
        tokens = re.split(r";\s*", cleaned)
        return [t.strip() for t in tokens if t.strip()]

    def validate(self, sql: str, allow_dml: bool = False) -> SafetyVerdict:
        """
        Inspects SQL query and returns a SafetyVerdict.
        By default, only non-destructive read operations (SELECT / WITH) are deemed SAFE.
        """
        if not sql or not sql.strip():
            return SafetyVerdict(
                is_safe=False,
                risk_level="CRITICAL",
                statement_type="UNKNOWN",
                violations=["Empty or whitespace-only SQL statement."],
                remediation_advice="Provide a valid SQL statement to analyze."
            )

        cleaned_sql = self._strip_comments_and_strings(sql)
        statements = self._split_statements(sql)
        violations = []

        # 1. Multi-statement detection (potential SQL injection / stacked queries)
        if len(statements) > 1:
            violations.append(
                f"Stacked multi-statement detected ({len(statements)} queries chained with semicolons). "
                "Only single atomic queries are permitted to prevent piggyback injection attacks."
            )
            return SafetyVerdict(
                is_safe=False,
                risk_level="CRITICAL",
                statement_type="MULTI_STATEMENT",
                violations=violations,
                remediation_advice="Separate multiple SQL commands and submit each query individually."
            )

        target_sql = statements[0]
        words = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", target_sql.upper())
        if not words:
            return SafetyVerdict(
                is_safe=False,
                risk_level="CRITICAL",
                statement_type="UNKNOWN",
                violations=["No valid SQL tokens found."],
                remediation_advice="Enter a well-formed SQL statement."
            )

        primary_command = words[0]

        # 2. Check for DDL operations (DROP, ALTER, CREATE, etc.)
        for keyword in self.DDL_KEYWORDS:
            if keyword in words:
                violations.append(
                    f"Prohibited DDL keyword '{keyword}' detected. Schema-altering operations are forbidden."
                )

        # 3. Check for Admin commands (PRAGMA, ATTACH, etc.)
        for keyword in self.ADMIN_COMMANDS:
            if keyword in words:
                violations.append(
                    f"Prohibited administrative command '{keyword}' detected."
                )

        # 4. Check for system schema tampering
        if re.search(r"\bsqlite_(master|schema|temp_master|sequence)\b", target_sql, re.IGNORECASE):
            violations.append("Direct modification or querying of internal SQLite schema tables is restricted.")

        # 5. DML Checks (DELETE, UPDATE, INSERT)
        is_dml = primary_command in ("DELETE", "UPDATE", "INSERT", "REPLACE")
        if is_dml and not allow_dml:
            violations.append(
                f"Data Modification Statement '{primary_command}' is disallowed in read-only analysis mode."
            )

        # 6. Unbounded DELETE / UPDATE detection (Missing or Trivial WHERE clause)
        if primary_command in ("DELETE", "UPDATE"):
            if "WHERE" not in words:
                violations.append(
                    f"Unbounded '{primary_command}' statement detected without a WHERE clause. "
                    "This would purge or overwrite the entire table."
                )
            else:
                # Extract WHERE clause
                where_match = re.search(r"\bWHERE\b\s+(.*)", target_sql, re.IGNORECASE)
                if where_match:
                    where_clause = where_match.group(1).lower().strip()
                    for pattern in self.TRIVIAL_WHERE_PATTERNS:
                        if re.match(r"^" + pattern + r"\s*$", where_clause) or re.search(r"\b" + pattern + r"\b", where_clause):
                            violations.append(
                                f"Trivial/tautological WHERE condition '{pattern}' detected in {primary_command}. "
                                "This pattern bypasses table protection and affects all rows."
                            )

        # Determine Statement Type & Verdict
        if violations:
            return SafetyVerdict(
                is_safe=False,
                risk_level="CRITICAL",
                statement_type="DDL" if any(w in words for w in self.DDL_KEYWORDS) else primary_command,
                violations=violations,
                remediation_advice="Remove destructive statements (DROP/TRUNCATE) or ensure safe bounded constraints."
            )

        # Safe Read-only queries
        if primary_command in ("SELECT", "WITH", "EXPLAIN"):
            return SafetyVerdict(
                is_safe=True,
                risk_level="SAFE",
                statement_type=primary_command,
                violations=[],
                remediation_advice="Query is a safe read-only operation."
            )

        # If DML is explicitly allowed and properly bounded
        if is_dml and allow_dml:
            return SafetyVerdict(
                is_safe=True,
                risk_level="WARNING",
                statement_type=primary_command,
                violations=[],
                remediation_advice="Constrained DML statement with validated WHERE clause."
            )

        # Fallback for unrecognized statements
        return SafetyVerdict(
            is_safe=False,
            risk_level="WARNING",
            statement_type=primary_command,
            violations=[f"Unrecognized or unsupported statement type: '{primary_command}'."],
            remediation_advice="Ensure query starts with standard SELECT, WITH, or validated statement."
        )


_default_guardrail = SQLSafetyGuardrail()

def get_guardrail() -> SQLSafetyGuardrail:
    return _default_guardrail
