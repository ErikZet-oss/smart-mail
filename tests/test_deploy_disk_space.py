"""Pilot 2026-11-23: backups before every update filled the disk and stopped Postgres. Backups are kept by count and
update.sh refuses to start without enough free space."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "deploy" / "lib.sh"


def _bash(script: str) -> str:
    return subprocess.check_output(["bash", "-c", f'set -euo pipefail\nsource "{LIB}"\n{script}'], text=True)


def test_prune_backups_keeps_the_newest_by_count(tmp_path: Path) -> None:
    stamps = [f"smartmail-202611{d:02d}T021500Z" for d in range(10, 22)]
    for s in stamps:
        (tmp_path / s).mkdir()
        (tmp_path / s / "db.dump").write_text("x")
    (tmp_path / "other").mkdir()  # never touched
    _bash(f'prune_backups "{tmp_path}" 5')
    left = sorted(p.name for p in tmp_path.iterdir())
    assert left == sorted([*stamps[-5:], "other"])


def test_prune_backups_default_and_invalid_keep(tmp_path: Path) -> None:
    for d in range(1, 9):
        (tmp_path / f"smartmail-2026110{d}T000000Z").mkdir()
    _bash(f'prune_backups "{tmp_path}"')  # SMARTMAIL_BACKUP_KEEP default 5
    assert len(list(tmp_path.iterdir())) == 5
    bad = subprocess.run(
        ["bash", "-c", f'source "{LIB}"; prune_backups "{tmp_path}" 0'], capture_output=True, text=True
    )
    assert bad.returncode != 0 and "SMARTMAIL_BACKUP_KEEP" in bad.stderr
    assert len(list(tmp_path.iterdir())) == 5


def test_free_gb_reports_a_number_for_a_missing_dir(tmp_path: Path) -> None:
    out = _bash(f'free_gb "{tmp_path}/does/not/exist/yet"')
    assert out.strip().isdigit()


def test_update_sh_checks_free_space_before_the_backup_and_prunes_after() -> None:
    src = (ROOT / "deploy" / "update.sh").read_text(encoding="utf-8")
    assert src.index("MIN_FREE_GB") < src.index('"$DEPLOY_DIR/backup.sh"')
    assert src.index("prune_backups") < src.index('"$DEPLOY_DIR/backup.sh"')
    assert "docker builder prune -f --filter until=72h" in src
    backup = (ROOT / "deploy" / "backup.sh").read_text(encoding="utf-8")
    assert "prune_backups" in backup and "-mtime +7" not in backup
