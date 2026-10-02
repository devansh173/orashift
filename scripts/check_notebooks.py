"""Static checks on the notebooks.

These notebooks run on Kaggle, not here: there is no GPU on the machine they were
written on. They therefore cannot be executed as part of the test suite, which
makes a syntax error the easiest way to waste somebody's 40-minute GPU session.

This script catches what can be caught without running anything: valid notebook
JSON, every code cell parsing as Python, and no output accidentally committed.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

NOTEBOOK_DIR = Path("notebooks")


def strip_magics(source: str) -> str:
    """Remove IPython magics and shell escapes, which are not valid Python."""
    lines = []
    for line in source.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("%", "!")):
            lines.append(" " * (len(line) - len(stripped)) + "pass")
        else:
            lines.append(line)
    return "\n".join(lines)


def check(path: Path) -> list[str]:
    problems: list[str] = []
    try:
        notebook = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{path}: invalid notebook JSON: {exc}"]

    code_cells = 0
    for index, cell in enumerate(notebook.get("cells", [])):
        if cell.get("cell_type") != "code":
            continue
        code_cells += 1

        if cell.get("outputs"):
            problems.append(f"{path}: cell {index} has committed output; clear it")

        source = "".join(cell.get("source", []))
        if not source.strip():
            problems.append(f"{path}: cell {index} is empty")
            continue

        try:
            ast.parse(strip_magics(source))
        except SyntaxError as exc:
            snippet = (exc.text or "").strip()[:80]
            problems.append(f"{path}: cell {index} line {exc.lineno}: {exc.msg}\n      {snippet}")

    if code_cells == 0:
        problems.append(f"{path}: no code cells")
    return problems


def main() -> int:
    notebooks = sorted(NOTEBOOK_DIR.glob("*.ipynb"))
    if not notebooks:
        print("no notebooks found", file=sys.stderr)
        return 1

    all_problems: list[str] = []
    for path in notebooks:
        problems = check(path)
        status = "OK" if not problems else f"{len(problems)} problem(s)"
        print(f"{path}: {status}")
        all_problems.extend(problems)

    for problem in all_problems:
        print(f"  {problem}", file=sys.stderr)
    return 1 if all_problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
