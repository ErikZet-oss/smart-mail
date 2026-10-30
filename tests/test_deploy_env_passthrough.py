"""Pilot: the API key and model ids were in deploy/.env (written by install.sh), but deploy/docker-compose.yml did not
pass them into the app and worker containers, so `ANTHROPIC_API_KEY` was None inside the app. Every setting that
install.sh writes for the app must reach the containers through the shared `x-app-env` block."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# install.sh keys for the deploy itself (Caddy/tunnel/compose); POSTGRES_PASSWORD reaches the app inside DATABASE_URL
DEPLOY_ONLY = {"APP_HOSTNAME", "DEPLOY_MODE", "CLOUDFLARE_TUNNEL_TOKEN", "POSTGRES_PASSWORD"}


def _app_env_keys() -> set[str]:
    text = (ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
    block = text.split("x-app-env: &app-env", 1)[1].split("\nservices:", 1)[0]
    return set(re.findall(r"^  ([A-Z][A-Z0-9_]+):", block, re.MULTILINE))


def _install_env_keys() -> set[str]:
    text = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    heredoc = text.split("<<EOF", 1)[1].split("\nEOF", 1)[0]
    return set(re.findall(r"^([A-Z][A-Z0-9_]+)=", heredoc, re.MULTILINE))


def test_ai_settings_reach_the_app_and_worker() -> None:
    keys = _app_env_keys()
    for name in (
        "LLM_PROVIDER",
        "ANTHROPIC_API_KEY",
        "LLM_MODEL_CLASSIFY",
        "LLM_MODEL_DRAFT",
        "LLM_MODEL_EXTRACT",
        "LLM_MODEL_ASSISTANT",
        "LLM_MODEL_EMBED",
        "AI_DAILY_BUDGET_USD",
    ):
        assert name in keys, f"{name} is not passed to the app containers (deploy/docker-compose.yml x-app-env)"


def test_every_app_setting_written_by_install_is_passed() -> None:
    missing = sorted(_install_env_keys() - _app_env_keys() - DEPLOY_ONLY)
    assert not missing, f"install.sh writes these to .env but the containers never see them: {missing}"


def test_129_eval_labels_survive_a_rebuild() -> None:
    """`eval_cli sample` writes to /var/lib/smartmail/eval; update.sh recreates the app container, so the labels must
    live in a named volume (deploy and dev compose) that the image creates owned by the app user."""
    for compose in ("deploy/docker-compose.yml", "docker-compose.yml"):
        text = (ROOT / compose).read_text(encoding="utf-8")
        app = text.split("\n  app:\n", 1)[1].split("\n  worker:", 1)[0]
        assert "smartmail_eval:/var/lib/smartmail/eval" in app, f"{compose}: app has no eval volume"
        top = text.rsplit("\nvolumes:\n", 1)[1]
        assert re.search(r"^  smartmail_eval:", top, re.MULTILINE), f"{compose}: volume not declared"
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "mkdir -p /var/lib/smartmail/eval" in dockerfile and "chown -R smartmail /var/lib/smartmail" in dockerfile
