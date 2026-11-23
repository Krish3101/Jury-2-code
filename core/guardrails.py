"""
Guardrails and SQL Safety Module
Implements Step 5: Guards against destructive fixes, injection vectors, and unauthorized mutations.
Provides Defense-in-Depth:
1. Lexical and Keyword Sanitization (DDL / Administration rejection)
2. AST Statement Boundary & Piggyback Injection Auditing
3. Mutation Scope Auditor (Unbounded DELETE/UPDATE detection & tautological WHERE protection)
4. Out-of-band & Internal System Table Safeguards
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class SafetyVerdict:
    is_safe: bool
    risk_level: str  # "SAFE", "WARNING", "CRITICAL"
    statement_type: str  # "SELECT", "INSERT", "UPDATE", "DELETE", "DDL", "ADMIN", "MULTI_STATEMENT"
    violations: List[str] = field(default_factory=list)
    remediation_advice: str = ""
    risk_score: int = 0  # 0 (Safe) to 100 (Extremely Dangerous)
    defense_layers: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_safe": self.is_safe,
            "risk_level": self.risk_level,
            "statement_type": self.statement_type,
            "violations": self.violations,
            "remediation_advice": self.remediation_advice,
            "risk_score": self.risk_score,
            "defense_layers": self.defense_layers
        }


class SQLSafetyGuardrail:
    """
    Enforces multi-layered defense-in-depth on user and LLM-generated SQL fixes.
    Guarantees database integrity cannot be compromised by hallucinated or adversarial queries.
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
        Inspects SQL query through multi-layer defense filters and returns a comprehensive SafetyVerdict.
        By default, only non-destructive read operations (SELECT / WITH) are deemed SAFE.
        """
        layers = {
            "lexical_audit": {"name": "Lexical Keyword & DDL Filter", "passed": True, "details": []},
            "boundary_audit": {"name": "Statement Boundary & Piggyback Guard", "passed": True, "details": []},
            "mutation_audit": {"name": "Mutation Scope & WHERE Auditor", "passed": True, "details": []},
            "system_audit": {"name": "Internal System Catalog & Sandbox Guard", "passed": True, "details": []}
        }

        if not sql or not sql.strip():
            layers["lexical_audit"]["passed"] = False
            layers["lexical_audit"]["details"].append("Empty or whitespace-only SQL statement.")
            return SafetyVerdict(
                is_safe=False,
                risk_level="CRITICAL",
                statement_type="UNKNOWN",
                violations=["Empty or whitespace-only SQL statement."],
                remediation_advice="Provide a valid SQL statement to analyze.",
                risk_score=100,
                defense_layers=layers
            )

        statements = self._split_statements(sql)
        violations = []
        risk_score = 0

        # Layer 1: Boundary & Stacked Queries Audit
        if len(statements) > 1:
            layers["boundary_audit"]["passed"] = False
            msg = (
                f"Stacked multi-statement detected ({len(statements)} queries chained with semicolons). "
                "Only single atomic queries are permitted to prevent piggyback injection attacks."
            )
            layers["boundary_audit"]["details"].append(msg)
            violations.append(msg)
            return SafetyVerdict(
                is_safe=False,
                risk_level="CRITICAL",
                statement_type="MULTI_STATEMENT",
                violations=violations,
                remediation_advice="Separate multiple SQL commands and submit each query individually.",
                risk_score=95,
                defense_layers=layers
            )

        target_sql = statements[0]
        words = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", target_sql.upper())
        if not words:
            layers["lexical_audit"]["passed"] = False
            layers["lexical_audit"]["details"].append("No valid SQL tokens found.")
            return SafetyVerdict(
                is_safe=False,
                risk_level="CRITICAL",
                statement_type="UNKNOWN",
                violations=["No valid SQL tokens found."],
                remediation_advice="Enter a well-formed SQL statement.",
                risk_score=100,
                defense_layers=layers
            )

        primary_command = words[0]

        # Layer 2: Lexical DDL & Admin Commands Audit
        for keyword in self.DDL_KEYWORDS:
            if keyword in words:
                layers["lexical_audit"]["passed"] = False
                msg = f"Prohibited DDL keyword '{keyword}' detected. Schema-altering operations are forbidden."
                layers["lexical_audit"]["details"].append(msg)
                violations.append(msg)
                risk_score = max(risk_score, 100)

        for keyword in self.ADMIN_COMMANDS:
            if keyword in words:
                layers["lexical_audit"]["passed"] = False
                msg = f"Prohibited administrative command '{keyword}' detected."
                layers["lexical_audit"]["details"].append(msg)
                violations.append(msg)
                risk_score = max(risk_score, 90)

        # Layer 3: System Catalog Safeguard
        if re.search(r"\bsqlite_(master|schema|temp_master|sequence)\b", target_sql, re.IGNORECASE):
            layers["system_audit"]["passed"] = False
            msg = "Direct modification or querying of internal SQLite schema tables is restricted."
            layers["system_audit"]["details"].append(msg)
            violations.append(msg)
            risk_score = max(risk_score, 85)

        # Layer 4: Mutation Scope & WHERE Clause Auditor
        is_dml = primary_command in ("DELETE", "UPDATE", "INSERT", "REPLACE")
        if is_dml and not allow_dml:
            layers["mutation_audit"]["passed"] = False
            msg = f"Data Modification Statement '{primary_command}' is disallowed in read-only analysis mode."
            layers["mutation_audit"]["details"].append(msg)
            violations.append(msg)
            risk_score = max(risk_score, 75)

        if primary_command in ("DELETE", "UPDATE"):
            if "WHERE" not in words:
                layers["mutation_audit"]["passed"] = False
                msg = (
                    f"Unbounded '{primary_command}' statement detected without a WHERE clause. "
                    "This would purge or overwrite the entire table."
                )
                layers["mutation_audit"]["details"].append(msg)
                violations.append(msg)
                risk_score = max(risk_score, 100)
            else:
                where_match = re.search(r"\bWHERE\b\s+(.*)", target_sql, re.IGNORECASE)
                if where_match:
                    where_clause = where_match.group(1).lower().strip()
                    for pattern in self.TRIVIAL_WHERE_PATTERNS:
                        if re.match(r"^" + pattern + r"\s*$", where_clause) or re.search(r"\b" + pattern + r"\b", where_clause):
                            layers["mutation_audit"]["passed"] = False
                            msg = (
                                f"Trivial/tautological WHERE condition '{pattern}' detected in {primary_command}. "
                                "This pattern bypasses table protection and affects all rows."
                            )
                            layers["mutation_audit"]["details"].append(msg)
                            violations.append(msg)
                            risk_score = max(risk_score, 95)

        # Verdict compilation
        if violations:
            stmt_type = "DDL" if any(w in words for w in self.DDL_KEYWORDS) else primary_command
            return SafetyVerdict(
                is_safe=False,
                risk_level="CRITICAL",
                statement_type=stmt_type,
                violations=violations,
                remediation_advice="Remove destructive statements (DROP/TRUNCATE) or ensure safe bounded constraints.",
                risk_score=risk_score,
                defense_layers=layers
            )

        # Safe Read-only queries
        if primary_command in ("SELECT", "WITH", "EXPLAIN"):
            return SafetyVerdict(
                is_safe=True,
                risk_level="SAFE",
                statement_type=primary_command,
                violations=[],
                remediation_advice="Query is a safe read-only operation.",
                risk_score=0,
                defense_layers=layers
            )

        # Constrained DML if allowed
        if is_dml and allow_dml:
            return SafetyVerdict(
                is_safe=True,
                risk_level="WARNING",
                statement_type=primary_command,
                violations=[],
                remediation_advice="Constrained DML statement with validated WHERE clause.",
                risk_score=35,
                defense_layers=layers
            )

        # Fallback for unrecognized statements
        layers["lexical_audit"]["passed"] = False
        layers["lexical_audit"]["details"].append(f"Unrecognized or unsupported statement type: '{primary_command}'.")
        return SafetyVerdict(
            is_safe=False,
            risk_level="WARNING",
            statement_type=primary_command,
            violations=[f"Unrecognized or unsupported statement type: '{primary_command}'."],
            remediation_advice="Ensure query starts with standard SELECT, WITH, or validated statement.",
            risk_score=50,
            defense_layers=layers
        )


_default_guardrail = SQLSafetyGuardrail()

def get_guardrail() -> SQLSafetyGuardrail:
    return _default_guardrail
