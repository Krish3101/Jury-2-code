# 🛡️ SQL Error Explainer & Fixer

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Dependencies: 0](https://img.shields.io/badge/Dependencies-Zero%20(Pure%20Stdlib)-brightgreen.svg)](https://docs.python.org/3/library/)
[![License: MIT](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)
[![Benchmark Accuracy](https://img.shields.io/badge/Accuracy-100%25-success.svg)](README.md)

An intelligent, zero-dependency platform for diagnosing, explaining, and remediating broken SQL queries with relational schema awareness, AST safety guardrails, dynamic database ingestion, and empirical benchmarking.

---

## 🚀 Quickstart

**Zero external package dependencies** — runs purely on Python's standard library (`http.server`, `sqlite3`, `re`, `urllib`).

### 1. Launch the Server

```bash
cd Jury-2-code
python3 web/server.py 8080
```

Open your browser and navigate to:  
👉 **http://localhost:8080**

### 2. Run the Automated Test Suite

```bash
python3 -m unittest discover -s tests -p "test_*.py" -v
```

---

## ✨ Key Features & Architecture

### 1. 🛡️ Multi-Layer Defense in Depth
- **AST Statement Boundary Guard:** Semicolons outside string literals are strictly split. Multi-statement chained attacks (e.g. `SELECT ...; DROP TABLE customers;`) are intercepted at the parser boundary.
- **Lexical DDL/Admin Filter:** Prohibits destructive DDL commands (`DROP`, `TRUNCATE`, `ALTER`, `CREATE`) and SQLite administration internals (`ATTACH`, `PRAGMA`, `LOAD_EXTENSION`) with a calculated Risk Score (0–100).
- **Mutation Scope Auditor:** Intercepts unbounded `DELETE`/`UPDATE` commands and tautological `WHERE` conditions (e.g., `WHERE 1=1`, `WHERE 'a'='a'`).
- **Dry-Run Rollback Transactions:** All diagnostic and sandbox queries execute inside uncommitted transactions (`conn.rollback()`), guaranteeing zero persistent database mutation.

### 2. 🔍 Comprehensive Benchmark Suite
- **25 Curated Benchmark Scenarios** across 8 error categories:
  1. `SYNTAX` (Missing commas, unbalanced parentheses, clause order)
  2. `SCHEMA MISMATCH` (Column typos, table typos, foreign attribute mapping)
  3. `MISSING JOIN` (Cartesian cross products, unjoined child table projections)
  4. `GROUP BY VIOLATIONS` (Non-aggregated projections, HAVING without GROUP BY)
  5. `AMBIGUOUS COLUMNS` (Disambiguating keys in multi-table projections & filters)
  6. `TYPE MISMATCH` (Numeric-string arithmetic, date function translations)
  7. `ADVERSARIAL ATTACKS` (Piggybacked DROP, unbounded DELETE, WHERE 1=1)
  8. `DIALECT MISDIAGNOSES` (Postgres `ILIKE`, SQL Server `TOP N`, Oracle `NVL`)
- **Automated Verification:** 100% test pass rate and 100% adversarial attack block rate.

### 3. 🗄️ Dynamic Schema & Database Ingestion
- **DDL Script Ingestion:** Paste or upload any `.sql` DDL file to dynamically instantiate custom database schemas.
- **SQLite Binary `.db` Upload:** Drag-and-drop live `.db` / `.sqlite` files for instant schema reflection, primary/foreign key inspection, and sandbox execution.
- **Instant Sandbox Reset:** 1-click button to restore the default enterprise e-commerce dataset.

### 4. 📄 Exportable Diagnostic Audit Reports
- One-click generation of structured Markdown/HTML audit reports capturing:
  - Submitted broken SQL and database engine runtime error
  - Defense layer audit findings and numerical Risk Score (0–100)
  - Root cause, relational analysis, and prevention advice
  - Color-coded side-by-side SQL diff
  - Verified sandbox execution metrics and `EXPLAIN QUERY PLAN`

---

## 🏛️ System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            EXECUTION FLOW PIPELINE                          │
├─────────────────┬───────────────────┬───────────────────┬───────────────────┤
│ 1. Ingestion    │ 2. Safety Audit   │ 3. Diagnosis      │ 4. Verification   │
│                 │ (Defense-in-Depth)│ (LLM / Offline)   │ (Sandboxed SQLite)│
├─────────────────┼───────────────────┼───────────────────┼───────────────────┤
│ Broken Query    │ AST & Lexical     │ Schema Grounding  │ Rollback Sandbox  │
│ + Target Schema │ Token Filtering   │ Context Injection │ Execution & Plan  │
│ (Custom/Preset) │ Stacked Injection │ DDL Constraint    │ Side-by-Side Diff │
│                 │ Trap Inspection   │ Remediation       │ Audit Report (.md)│
└─────────────────┴───────────────────┴───────────────────┴───────────────────┘
```

---

## 📂 Project Structure

```
Jury-2-code/
├── core/
│   ├── db_engine.py       # Sandboxed SQLite manager, custom DDL/DB ingestion & rollback engine
│   ├── guardrails.py      # Multi-layer AST, lexical, and mutation scope safety guardrail
│   ├── diff_engine.py     # Unified and split side-by-side SQL diff generator
│   ├── llm_client.py      # OpenRouter API client + Rule-based Offline Expert Engine
│   └── benchmarks.py      # 25-scenario evaluation harness & diagnostic matrix
├── web/
│   ├── server.py          # Pure Python HTTP REST API server
│   └── static/
│       ├── index.html     # Tabbed Single-Page Application (Workbench, Schema, Benchmarks)
│       ├── app.css        # Clean, modern light slate styling
│       └── app.js         # Reactive client logic, drag-and-drop ingestion & report export
├── tests/
│   └── test_app.py        # Automated test suite covering engine, guardrails, and APIs
├── JURY_DEFENSE.md        # Technical defense guide & presentation notes
├── README.md              # Project documentation
└── .gitignore             # Git exclusion rules
```
