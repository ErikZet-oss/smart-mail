"""ClamAV soft-fail scanning (Phase 1h): clean / infected / unreachable → skipped."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import Settings
from app.mail.clamav import scan_bytes


@pytest.mark.asyncio
async def test_clamav_disabled_host_skips() -> None:
    assert await scan_bytes(Settings(clamav_host="off"), b"x") == "skipped"
    assert await scan_bytes(Settings(clamav_host=""), b"x") == "skipped"


@pytest.mark.asyncio
async def test_clamav_unreachable_skips() -> None:
    with patch("app.mail.clamav._instream", side_effect=OSError("refused")):
        assert await scan_bytes(Settings(clamav_host="clamav"), b"x") == "skipped"


@pytest.mark.asyncio
async def test_clamav_clean_and_infected() -> None:
    with patch("app.mail.clamav._instream", new=AsyncMock(return_value="clean")):
        assert await scan_bytes(Settings(clamav_host="clamav"), b"ok") == "clean"
    with patch("app.mail.clamav._instream", new=AsyncMock(return_value="infected")):
        assert await scan_bytes(Settings(clamav_host="clamav"), b"eicar") == "infected"
