"""Every nginx config that serves the SPA must serve the pdf.js worker (.mjs) as JavaScript (pilot: W2l failed on the
test server because only web/nginx.conf had the rule; deploy uses deploy/nginx-deploy.*.conf)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = [ROOT / "web" / "nginx.conf", *sorted((ROOT / "deploy").glob("nginx-deploy.*.conf"))]


@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: str(p.relative_to(ROOT)))
def test_mjs_is_served_as_javascript_with_strict_csp(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    block = re.search(r"location ~\* \\\.mjs\$ \{(?P<body>.*?)\n  \}", text, re.DOTALL)
    assert block is not None, f"{path.name}: no .mjs location"
    body = block.group("body")
    assert "default_type text/javascript;" in body
    assert "script-src 'self'" in body and "nosniff" in body


def test_all_spa_configs_are_checked() -> None:
    assert len(CONFIGS) >= 3  # web dev/CI + vps + tunnel
