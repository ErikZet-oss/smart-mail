"""Pilot: uploading a person photo answered 500 on the server: `ModuleNotFoundError: No module named 'PIL'`. Pillow
was only in the dev dependency group, and the Docker image installs `uv sync --no-dev`, so tests passed locally and in
CI while production code could not import it. Every package that runtime code (`app/`) imports must be a project
dependency, never a dev-only one."""

from __future__ import annotations

import ast
import re
import tomllib
from importlib.metadata import packages_distributions
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _names(specs: list[str]) -> set[str]:
    return {re.split(r"[\s\[<>=!~;]", spec, maxsplit=1)[0].lower().replace("_", "-") for spec in specs}


def _top_level_imports(root: Path) -> set[str]:
    found: set[str] = set()
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    return found


def test_runtime_code_imports_no_dev_only_package() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    runtime = _names(project["project"]["dependencies"])
    dev_only = _names(project["dependency-groups"]["dev"]) - runtime
    dists = packages_distributions()
    offenders = sorted(
        f"{module} ({dist})"
        for module in _top_level_imports(ROOT / "app")
        for dist in (d.lower().replace("_", "-") for d in dists.get(module, []))
        if dist in dev_only
    )
    assert not offenders, f"app/ imports dev-only packages (missing in the Docker image): {offenders}"


def test_pillow_is_a_runtime_dependency() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "pillow" in _names(project["project"]["dependencies"])
