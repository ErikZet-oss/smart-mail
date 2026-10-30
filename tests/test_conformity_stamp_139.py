"""#139 Settings 11: branch „Pečiatka“ and person „Podpis“ — transparent PNG, admin + re-auth, audited, never public."""

from __future__ import annotations

import io

from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Branch, Person, Role
from app.core.audit import AuditLog
from tests.conftest import Client, FakeMailServer, make_branch, make_personal
from tests.test_branches_people_55 import PASSWORD, _upload


def transparent_png(width: int = 300, height: int = 200) -> bytes:
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for x in range(20, width - 20):
        image.putpixel((x, height // 2), (20, 40, 160, 255))  # a fictional stamp line
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def opaque_png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (50, 50), "white").save(out, format="PNG")
    return out.getvalue()


async def _login(client: Client, db: AsyncSession, mail_server: FakeMailServer, role: Role = Role.admin) -> None:
    acc = await make_personal(db, email=f"{role.value}@smartsro.sk", role=role)
    mail_server.passwords[acc.email] = PASSWORD
    assert (await client.login(acc.email, PASSWORD)).status_code == 200


async def test_139_stamp_upload_needs_reauth_and_is_audited(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _login(client, db, mail_server)
    branch, _ = await make_branch(db, "Nitra")
    url = f"/api/settings/admin/branches/{branch.id}/stamp"
    r = await _upload(client, url, "peciatka.png", transparent_png())
    assert r.status_code == 401 and r.json()["detail"]["code"] == "reauth_required"
    assert (await client.reauth(PASSWORD)).status_code == 200
    r = await _upload(client, url, "peciatka.png", transparent_png(3000, 2000))
    assert r.status_code == 200 and r.json() == {"has_stamp": True}
    stored = await db.scalar(select(Branch).where(Branch.id == branch.id).execution_options(populate_existing=True))
    assert stored is not None and stored.stamp_key
    preview = await client.get(url)
    assert preview.status_code == 200 and preview.headers["cache-control"] == "no-store"
    with Image.open(io.BytesIO(preview.content)) as img:
        assert max(img.size) == 1200 and img.mode == "RGBA"  # scaled down, transparency kept
    branches = (await client.get("/api/settings/admin/branches")).json()
    assert next(b for b in branches if b["id"] == str(branch.id))["has_stamp"] is True

    assert (await client.send_json("DELETE", url)).json() == {"has_stamp": False}
    actions = list((await db.scalars(select(AuditLog.action))).all())
    assert "settings.stamp_saved" in actions and "settings.stamp_removed" in actions


async def test_139_signature_upload_and_preview(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    await _login(client, db, mail_server)
    assert (await client.reauth(PASSWORD)).status_code == 200
    manager = await make_personal(db, email="veduci@smartsro.sk")
    url = f"/api/settings/admin/people/{manager.person_id}/signature"
    assert (await _upload(client, url, "podpis.png", transparent_png())).json() == {"has_signature": True}
    person = await db.scalar(
        select(Person).where(Person.id == manager.person_id).execution_options(populate_existing=True)
    )
    assert person is not None and person.signature_key
    assert (await client.get(url)).status_code == 200
    actions = list((await db.scalars(select(AuditLog.action))).all())
    assert "settings.signature_saved" in actions


async def test_139_only_transparent_png(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    await _login(client, db, mail_server)
    assert (await client.reauth(PASSWORD)).status_code == 200
    branch, _ = await make_branch(db, "Senica")
    url = f"/api/settings/admin/branches/{branch.id}/stamp"
    jpeg = io.BytesIO()
    Image.new("RGB", (20, 20), "red").save(jpeg, format="JPEG")
    assert (await _upload(client, url, "a.jpg", jpeg.getvalue(), "image/jpeg")).json()["detail"]["code"] == (
        "image_png_required"
    )
    assert (await _upload(client, url, "a.png", opaque_png())).json()["detail"]["code"] == "image_not_transparent"
    big = b"\x89PNG" + b"0" * (1024 * 1024 + 10)
    assert (await _upload(client, url, "big.png", big)).json()["detail"]["code"] == "image_too_large"


async def test_139_stamp_and_signature_are_never_public(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _login(client, db, mail_server)
    assert (await client.reauth(PASSWORD)).status_code == 200
    branch, _ = await make_branch(db, "Trenčín")
    await _upload(client, f"/api/settings/admin/branches/{branch.id}/stamp", "p.png", transparent_png())
    await client.post("/api/auth/logout")
    other = Client(transport=client._transport, base_url=str(client.base_url))
    for url in (
        f"/api/settings/admin/branches/{branch.id}/stamp",
        f"/api/settings/branches/{branch.id}/stamp",  # no public twin of the logo URL
    ):
        assert (await other.get(url)).status_code in (401, 403, 404)


async def test_139_non_admin_cannot_upload_or_preview(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _login(client, db, mail_server, role=Role.sales)
    assert (await client.reauth(PASSWORD)).status_code == 200
    branch, _ = await make_branch(db, "Trnava")
    url = f"/api/settings/admin/branches/{branch.id}/stamp"
    assert (await _upload(client, url, "p.png", transparent_png())).status_code == 403
    assert (await client.get(url)).status_code == 403
