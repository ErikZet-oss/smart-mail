"""Pilot: a person's photo was uploaded in Settings 11b, but „Kto ste?“ (W1b) and the PersonChip still showed the
initials — the picker API did not carry the photo (UX_SPEC W1b: avatar = photo or initials)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import Client, FakeMailServer
from tests.test_branches_people_55 import _admin, _png, _upload
from tests.test_persons_1b import login_branch, senica


async def test_picker_and_me_carry_the_person_photo(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _admin(client, db, mail_server)
    _, acc, people = await senica(db)
    jana = people["jana"]
    r = await _upload(client, f"/api/settings/admin/people/{jana.id}/photo", "jana.png", _png(300, 300))
    assert r.status_code == 200, r.text

    client.cookies.clear()
    await login_branch(client, mail_server, acc)
    picker = (await client.get("/api/auth/persons")).json()
    by_id = {p["id"]: p for p in picker["persons"]}
    url = by_id[str(jana.id)]["photo_url"]
    assert url and url.startswith(f"/api/settings/people/{jana.id}/photo")
    assert by_id[str(people["marek"].id)]["photo_url"] is None
    # the photo is readable before a person is chosen (the picker shows it)
    served = await client.get(url)
    assert served.status_code == 200 and served.headers["content-type"] == "image/jpeg"

    r = await client.send_json("POST", "/api/auth/person", {"person_id": str(jana.id), "remember_device": False})
    assert r.status_code == 200
    assert r.json()["person"]["photo_url"] == url
