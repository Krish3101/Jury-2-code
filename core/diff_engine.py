import difflib
from typing import Any, Dict, List


def generate_unified_diff(original_sql: str, fixed_sql: str) -> str:
    orig_lines = [line + "\n" for line in original_sql.strip().splitlines()]
    fixed_lines = [line + "\n" for line in fixed_sql.strip().splitlines()]
    diff = difflib.unified_diff(
        orig_lines,
        fixed_lines,
        fromfile="Original Broken SQL",
        tofile="Corrected SQL",
        lineterm="\n"
    )
    return "".join(diff)


def generate_structured_diff(original_sql: str, fixed_sql: str) -> Dict[str, Any]:
    orig_lines = [line.rstrip() for line in original_sql.strip().splitlines()]
    fixed_lines = [line.rstrip() for line in fixed_sql.strip().splitlines()]

    matcher = difflib.SequenceMatcher(None, orig_lines, fixed_lines)
    orig_view: List[Dict[str, Any]] = []
    fixed_view: List[Dict[str, Any]] = []
    
    orig_line_no = 1
    fixed_line_no = 1

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for i in range(i1, i2):
                orig_view.append({
                    "line_no": orig_line_no,
                    "text": orig_lines[i],
                    "status": "unchanged"
                })
                fixed_view.append({
                    "line_no": fixed_line_no,
                    "text": fixed_lines[j1 + (i - i1)],
                    "status": "unchanged"
                })
                orig_line_no += 1
                fixed_line_no += 1
        elif tag == "replace":
            for i in range(i1, i2):
                orig_view.append({
                    "line_no": orig_line_no,
                    "text": orig_lines[i],
                    "status": "removed"
                })
                orig_line_no += 1
            for j in range(j1, j2):
                fixed_view.append({
                    "line_no": fixed_line_no,
                    "text": fixed_lines[j],
                    "status": "added"
                })
                fixed_line_no += 1
        elif tag == "delete":
            for i in range(i1, i2):
                orig_view.append({
                    "line_no": orig_line_no,
                    "text": orig_lines[i],
                    "status": "removed"
                })
                orig_line_no += 1
        elif tag == "insert":
            for j in range(j1, j2):
                fixed_view.append({
                    "line_no": fixed_line_no,
                    "text": fixed_lines[j],
                    "status": "added"
                })
                fixed_line_no += 1

    return {
        "unified_text": generate_unified_diff(original_sql, fixed_sql),
        "left_lines": orig_view,
        "right_lines": fixed_view,
        "changes_count": sum(1 for line in orig_view if line["status"] == "removed") +
                         sum(1 for line in fixed_view if line["status"] == "added")
    }
