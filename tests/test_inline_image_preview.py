"""Pilot: a pasted screenshot (#119) showed as a broken image in the compose editor. The body keeps `src="cid:…"`
(the related MIME part of the sent mail), which a browser can't load. The editor now loads its own copy from
`GET /api/mail/compose/{draft}/inline/{content_id}`."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import Client, FakeMailServer
from tests.test_branches_people_55 import _png
from tests.test_compose_1e import _signed_in
from tests.test_presend_2d import _draft


async def _upload_inline(client: Client, draft_id: str, data: bytes) -> dict[str, object]:
    await client.csrf()
    r = await client.post(
        f"/api/mail/compose/{draft_id}/attachments",
        files={"file": ("snimka.png", data, "image/png")},
        data={"inline": "true"},
        headers={"X-CSRF-Token": client.cookies["sm_csrf"]},
    )
    assert r.status_code == 200, r.text
    att = next(a for a in r.json()["attachments"] if a.get("content_id"))
    return dict(att)


async def test_inline_image_preview_serves_the_drafts_own_image(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _signed_in(client, db, mail_server)
    draft = await _draft(client)
    png = _png(20, 10)
    att = await _upload_inline(client, draft["id"], png)
    r = await client.get(f"/api/mail/compose/{draft['id']}/inline/{att['content_id']}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.content == png


async def test_inline_image_preview_unknown_cid_or_other_draft_is_404(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _signed_in(client, db, mail_server)
    draft = await _draft(client)
    att = await _upload_inline(client, draft["id"], _png(5, 5))
    assert (await client.get(f"/api/mail/compose/{draft['id']}/inline/nope@smartmail")).status_code == 404
    other = await _draft(client)
    assert (await client.get(f"/api/mail/compose/{other['id']}/inline/{att['content_id']}")).status_code == 404
