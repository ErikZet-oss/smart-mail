"""Deploy edge configs: CF-Connecting-IP only in tunnel mode; Caddy strips it in vps (D26)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"


def test_caddy_strips_cf_connecting_ip_in_vps() -> None:
    text = (DEPLOY / "Caddyfile.tpl").read_text()
    assert "header_up -CF-Connecting-IP" in text
    assert "reverse_proxy web:80" in text


def test_vps_nginx_ignores_cf_connecting_ip() -> None:
    text = (DEPLOY / "nginx-deploy.vps.conf").read_text()
    assert "$http_cf_connecting_ip" not in text
    assert "$proxy_add_x_forwarded_for" in text


def test_tunnel_nginx_uses_cf_connecting_ip() -> None:
    text = (DEPLOY / "nginx-deploy.tunnel.conf").read_text()
    assert "$http_cf_connecting_ip" in text
    assert "$proxy_add_x_forwarded_for" in text


def test_render_edge_configs_writes_nginx_active_not_templates() -> None:
    script = f"""
set -euo pipefail
source "{DEPLOY}/lib.sh"
VPS_BEFORE="$(sha256sum "{DEPLOY}/nginx-deploy.vps.conf" | awk '{{print $1}}')"
DEPLOY_MODE=ci render_edge_configs
test -f "{DEPLOY}/nginx-active.conf"
grep -q 'proxy_add_x_forwarded_for' "{DEPLOY}/nginx-active.conf"
! grep -q 'http_cf_connecting_ip' "{DEPLOY}/nginx-active.conf"
# templates in git must stay untouched
VPS_AFTER="$(sha256sum "{DEPLOY}/nginx-deploy.vps.conf" | awk '{{print $1}}')"
[[ "$VPS_BEFORE" == "$VPS_AFTER" ]]
DEPLOY_MODE=tunnel render_edge_configs
grep -q 'http_cf_connecting_ip' "{DEPLOY}/nginx-active.conf"
DEPLOY_MODE=vps APP_HOSTNAME=test.example render_edge_configs
grep -q 'header_up -CF-Connecting-IP' "{DEPLOY}/Caddyfile"
grep -q 'test.example' "{DEPLOY}/Caddyfile"
! grep -q 'http_cf_connecting_ip' "{DEPLOY}/nginx-active.conf"
DEPLOY_MODE=ci render_edge_configs
"""
    subprocess.run(["bash", "-c", script], check=True, env=os.environ.copy(), cwd=str(DEPLOY.parent))
