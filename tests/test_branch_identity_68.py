"""Issue #68: on a branch login the admin sets the sender of the branch identity (login smartsronitra@ sends as the
alias nitra@); others get 403; the address must be a company one; the signature preview shows the identity e-mail."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Person, Role
from app.core.audit import AuditLog
from tests.conftest import Client, FakeMailServer
from tests.test_persons_1b import choose, login_branch, senica

TEMPLATE = {"sk": "<p>{meno} {priezvisko} · {email_pobocky}</p>"}


async def _branch_identity(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, *, as_admin: bool
) -> dict[str, Any]:
    branch, acc, people = await senica(db, signature_template_html=TEMPLATE)
    admin = Person(branch_id=branch.id, first_name="Erik", last_name="Správca", role=Role.admin)
    db.add(admin)
    await db.commit()
    await login_branch(client, mail_server, acc)
    await choose(client, admin if as_admin else people["jana"])
    listed = await client.get("/api/mail/mailboxes/default/identities")  # creates the default identity
    assert listed.status_code == 200, listed.text
    identities = (await client.get("/api/settings/mailboxes/default/identities")).json()
    identity: dict[str, Any] = identities[0]
    return identity


def _payload(identity: dict[str, Any], **changes: Any) -> dict[str, Any]:
    body = {
        "display_name": identity["display_name"],
        "email": identity["email"],
        "organization": identity.get("organization"),
        "reply_to": identity.get("reply_to"),
        "bcc": identity.get("bcc") or [],
        "is_default": True,
        "signature_html": {},
    }
    body.update(changes)
    return body


async def test_68_admin_sets_the_sender_of_the_branch_identity(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    identity = await _branch_identity(client, db, mail_server, as_admin=True)
    r = await client.send_json(
        "PUT",
        f"/api/settings/identities/{identity['id']}",
        _payload(identity, email="nitra@smartsro.sk", display_name="Smart s.r.o. – pobočka Nitra"),
    )
    assert r.status_code == 200, r.text
    assert (r.json()["email"], r.json()["display_name"]) == ("nitra@smartsro.sk", "Smart s.r.o. – pobočka Nitra")
    row = (
        await db.execute(
            select(AuditLog)
            .where(AuditLog.action == "settings.identity_saved")
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert row.details["before"]["email"] == identity["email"]
    assert row.details["after"]["email"] == "nitra@smartsro.sk"

    # the preview of the branch signature uses the identity e-mail, like compose does
    context = (await client.get("/api/settings/mailboxes/default/signature-context")).json()
    assert context["branch_managed"] is True
    assert "nitra@smartsro.sk" in context["preview_html"]
    assert identity["email"] not in context["preview_html"]


async def test_68_non_admin_cannot_change_the_branch_identity(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    identity = await _branch_identity(client, db, mail_server, as_admin=False)
    r = await client.send_json(
        "PUT", f"/api/settings/identities/{identity['id']}", _payload(identity, email="nitra@smartsro.sk")
    )
    assert r.status_code == 403 and r.json()["detail"]["code"] == "admin_required"


async def test_68_branch_sender_must_be_a_company_address(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    identity = await _branch_identity(client, db, mail_server, as_admin=True)
    for changes in ({"email": "nitra@gmail.example"}, {"reply_to": "x@evil.example"}):
        r = await client.send_json("PUT", f"/api/settings/identities/{identity['id']}", _payload(identity, **changes))
        assert r.status_code == 422 and r.json()["detail"]["code"] == "identity_email_not_internal", changes
