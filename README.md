# SQL Error Explainer & Fixer

An intelligent web platform for diagnosing, explaining, and remediating broken SQL queries with schema awareness and AST safety guardrails.

## 🚀 Quickstart

No external packages or `pip install` required — runs purely on the Python standard library.

### 1. Start the Web Application

```bash
python3 web/server.py 8080
```

Open your browser and navigate to:
👉 **http://localhost:8080**

### 2. (Optional) Configure Model

By default, the platform uses a built-in **Offline Expert Engine** that requires no API keys or internet connection.

To use cloud LLMs (such as `openrouter/free` or `qwen/qwen-2.5-coder-32b-instruct:free`):
1. Click **Model Config** in the top navigation bar of the web UI.
2. Enter your OpenRouter API key and select your preferred model.
3. Click **Save Settings**.

---

## 🧪 Run Tests

Execute the automated test suite:

```bash
python3 -m unittest discover -s tests -p "test_*.py" -v
```

---

## ✨ Features

- **Schema-Grounded Diagnostics**: Analyzes relational schema (tables, columns, foreign keys) to detect syntax errors, typos, missing joins, and group by violations.
- **Side-by-Side Diff Visualizer**: Color-coded unified and split diff highlighting exact SQL corrections.
- **AST Security Guardrails**: Intercepts and blocks destructive DDL/DML operations (`DROP`, `TRUNCATE`, unbounded `DELETE`/`UPDATE`, and stacked SQL injections).
- **Embedded SQLite Sandbox**: Safely validates fixes and executes queries in an isolated database environment.
- **One-Click Scenario Presets**: Quick preset scenarios (missing comma, column typo, missing join, injection attacks) for instant testing.
