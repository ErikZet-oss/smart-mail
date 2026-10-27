#!/usr/bin/env python3
"""Import Roundcube contacts (vCard), identities and Odpovede into Smart Mail (Phase 1h-e).

Read-only against Roundcube: never writes to the Roundcube DB. Does **not** import filters
(ManageSieve stays the source of truth for Filtre / Mimo kancelárie).

Fictional fixtures only in git (`@smartmail.test`). Never commit real customer exports.

Examples::

    # Dry-run against fixtures (CI / local)
    uv run python tools/roundcube_import.py \\
      --vcard fixtures/contacts/roundcube_export.vcf \\
      --identities fixtures/roundcube/identities.json \\
      --responses fixtures/roundcube/responses.json \\
      --account pilot@smartmail.test --dry-run

    # Apply into the local Smart Mail DB (test mailbox)
    DATABASE_URL=… uv run python tools/roundcube_import.py \\
      --vcard fixtures/contacts/roundcube_export.vcf \\
      --identities fixtures/roundcube/identities.json \\
      --responses fixtures/roundcube/responses.json \\
      --account pilot@smartmail.test --apply

    # Optional live Roundcube MySQL/MariaDB (SELECT only)
    uv run python tools/roundcube_import.py \\
      --roundcube-dsn "mysql+pymysql://ro_user@127.0.0.1/roundcube" \\
      --roundcube-user-email pilot@smartmail.test \\
      --account pilot@smartmail.test --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ALLOWED_FIXTURE_DOMAINS = ("smartmail.test", "smartsro.sk", "example.com", "example.test")


@dataclass
class IdentityRow:
    email: str
    name: str
    organization: str | None = None
    reply_to: str | None = None
    bcc: list[str] = field(default_factory=list)
    is_default: bool = False
    signature_html: dict[str, str] = field(default_factory=dict)


@dataclass
class ResponseRow:
    name: str
    body_html: str
    language: str = "sk"
    shared: bool = False


def _email_ok_for_fixture(email: str) -> bool:
    host = email.rsplit("@", 1)[-1].lower()
    return any(host == d or host.endswith("." + d) for d in ALLOWED_FIXTURE_DOMAINS)


def identities_from_dicts(raw: list[dict[str, Any]]) -> list[IdentityRow]:
    out: list[IdentityRow] = []
    for item in raw:
        email = str(item.get("email") or "").strip()
        name = str(item.get("name") or "").strip() or email
        if not email:
            continue
        sig_html = item.get("signature_html")
        signature = item.get("signature") or ""
        html_flag = int(item.get("html_signature") or 0)
        if isinstance(sig_html, dict):
            sig_map = {str(k): str(v) for k, v in sig_html.items()}
        elif isinstance(sig_html, str) and sig_html.strip():
            sig_map = {"sk": sig_html}
        elif html_flag and signature:
            sig_map = {"sk": signature if "<" in signature else f"<p>{signature}</p>"}
        elif signature:
            sig_map = {"sk": "<p>" + signature.replace("\n", "<br>") + "</p>"}
        else:
            sig_map = {}
        bcc_raw = item.get("bcc") or ""
        bcc = [b.strip() for b in str(bcc_raw).split(",") if b.strip()] if bcc_raw else []
        out.append(
            IdentityRow(
                email=email,
                name=name,
                organization=(str(item["organization"]).strip() if item.get("organization") else None),
                reply_to=(str(item["reply_to"]).strip() if item.get("reply_to") else None),
                bcc=bcc,
                is_default=bool(int(item.get("standard") or 0)),
                signature_html=sig_map,
            )
        )
    return out


def load_identities_json(path: Path) -> list[IdentityRow]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise SystemExit(f"identities file must be a JSON array: {path}")
    return identities_from_dicts(raw)


def responses_from_dicts(raw: list[dict[str, Any]]) -> list[ResponseRow]:
    out: list[ResponseRow] = []
    for item in raw:
        name = str(item.get("name") or "").strip()
        data = str(item.get("data") or "")
        if not name or not data:
            continue
        is_html = bool(int(item.get("is_html") or 0))
        body = data if is_html or "<" in data else f"<p>{data.replace(chr(10), '<br>')}</p>"
        out.append(
            ResponseRow(
                name=name[:80],
                body_html=body[:20_000],
                language=str(item.get("language") or "sk")[:8],
                shared=bool(item.get("shared")),
            )
        )
    return out


def load_responses_json(path: Path) -> list[ResponseRow]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise SystemExit(f"responses file must be a JSON array: {path}")
    return responses_from_dicts(raw)


def load_vcard_summary(path: Path) -> list[str]:
    from app.contacts.vcard import parse_vcards

    text = path.read_text(encoding="utf-8", errors="replace")
    contacts = parse_vcards(text)
    return [f"{c.display_name} <{(c.emails[0]['email'] if c.emails else '')}>" for c in contacts]


def load_identities_from_roundcube_dsn(dsn: str, user_email: str) -> list[IdentityRow]:
    """SELECT-only read of Roundcube ``identities`` (optional live source)."""
    try:
        import sqlalchemy as sa
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("sqlalchemy required for --roundcube-dsn") from exc

    engine = sa.create_engine(dsn)
    sql = sa.text(
        """
        SELECT i.name, i.email, i.organization, i.`reply-to` AS reply_to, i.bcc,
               i.standard, i.signature, i.html_signature
        FROM identities i
        JOIN users u ON u.user_id = i.user_id
        WHERE i.del = 0 AND u.username = :username
        ORDER BY i.standard DESC, i.identity_id
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql, {"username": user_email}).mappings().all()
    mapped: list[dict[str, Any]] = [
        {
            "email": r["email"],
            "name": r["name"] or r["email"],
            "organization": r["organization"],
            "reply_to": r["reply_to"],
            "bcc": r["bcc"] or "",
            "standard": r["standard"],
            "signature": r["signature"] or "",
            "html_signature": r["html_signature"],
        }
        for r in rows
    ]
    return identities_from_dicts(mapped)


def load_responses_from_roundcube_dsn(dsn: str, user_email: str) -> list[ResponseRow]:
    try:
        import sqlalchemy as sa
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("sqlalchemy required for --roundcube-dsn") from exc

    engine = sa.create_engine(dsn)
    sql = sa.text(
        """
        SELECT r.name, r.data, r.is_html
        FROM responses r
        JOIN users u ON u.user_id = r.user_id
        WHERE r.del = 0 AND u.username = :username
        ORDER BY r.response_id
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql, {"username": user_email}).mappings().all()
    mapped = [
        {"name": r["name"], "data": r["data"] or "", "is_html": r["is_html"], "language": "sk"} for r in rows
    ]
    return responses_from_dicts(mapped)


def print_plan(
    *,
    account: str,
    vcard_names: list[str],
    identities: list[IdentityRow],
    responses: list[ResponseRow],
) -> None:
    print(f"Account: {account}")
    print(f"vCard contacts: {len(vcard_names)}")
    for n in vcard_names[:20]:
        print(f"  - {n}")
    if len(vcard_names) > 20:
        print(f"  … +{len(vcard_names) - 20} more")
    print(f"Identities: {len(identities)}")
    for i in identities:
        print(f"  - {i.name} <{i.email}> default={i.is_default}")
    print(f"Odpovede: {len(responses)}")
    for r in responses:
        print(f"  - {r.name} ({r.language}) shared={r.shared}")
    print("Filters: skipped (not imported — ManageSieve remains source of truth)")


async def apply_import(
    *,
    database_url: str,
    account_email: str,
    vcard_text: str | None,
    identities: list[IdentityRow],
    responses: list[ResponseRow],
) -> dict[str, int]:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.auth.models import Account, Person
    from app.contacts import service as contacts_service
    from app.contacts.vcard import parse_vcards
    from app.core.config import Settings
    from app.mail.compose_models import CannedResponse, Identity
    from app.mail.mailboxes import ensure_own_mailbox
    from app.mail.sanitize import sanitize_html

    with tempfile.TemporaryDirectory(prefix="sm-import-") as tmp:
        settings = Settings(
            database_url=database_url,
            app_env="test",
            storage_backend="local",
            storage_path=tmp,
        )
        engine = create_async_engine(settings.database_url)
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
        stats = {"contacts_created": 0, "identities_upserted": 0, "responses_created": 0}

        async with sessionmaker() as db:
            account = (
                await db.execute(select(Account).where(Account.email == account_email.lower()))
            ).scalar_one_or_none()
            if account is None:
                raise SystemExit(f"account not found: {account_email}")
            if account.person_id is None:
                raise SystemExit(
                    f"account {account_email} has no person_id (branch logins need an active person first)"
                )
            person = await db.get(Person, account.person_id)
            if person is None:
                raise SystemExit(f"person {account.person_id} missing")
            mailbox = await ensure_own_mailbox(db, account, settings)

            if vcard_text is not None:
                personal, _shared = await contacts_service.ensure_default_books(db, person.id)
                for c in parse_vcards(vcard_text):
                    for em in c.emails:
                        addr = str(em.get("email") or "")
                        if addr and not _email_ok_for_fixture(addr):
                            raise SystemExit(f"refusing non-fixture contact email: {addr}")
                result = await contacts_service.import_vcard(db, personal, vcard_text, on_duplicate="skip")
                stats["contacts_created"] = int(result.get("created", 0))

            for row in identities:
                if not _email_ok_for_fixture(row.email):
                    raise SystemExit(f"refusing non-fixture identity email: {row.email}")
                twins = list(
                    (
                        await db.execute(
                            select(Identity).where(
                                Identity.mailbox_id == mailbox.id, Identity.display_name == row.name
                            )
                        )
                    ).scalars()
                )
                existing = twins[0] if twins else None
                if existing is None:
                    db.add(
                        Identity(
                            mailbox_id=mailbox.id,
                            display_name=row.name[:100],
                            email=row.email.lower(),
                            organization=row.organization,
                            reply_to=row.reply_to,
                            bcc=row.bcc,
                            is_default=row.is_default,
                            signature_html=row.signature_html,
                        )
                    )
                else:
                    existing.email = row.email.lower()
                    existing.organization = row.organization
                    existing.reply_to = row.reply_to
                    existing.bcc = row.bcc
                    existing.is_default = row.is_default
                    if row.signature_html:
                        existing.signature_html = row.signature_html
                stats["identities_upserted"] += 1

            for row in responses:
                dup = (
                    await db.execute(
                        select(CannedResponse).where(
                            CannedResponse.person_id == person.id, CannedResponse.name == row.name
                        )
                    )
                ).scalar_one_or_none()
                if dup is not None:
                    continue
                db.add(
                    CannedResponse(
                        person_id=person.id,
                        name=row.name,
                        language=row.language,
                        body_html=sanitize_html(row.body_html),
                        shared=row.shared,
                    )
                )
                stats["responses_created"] += 1

            await db.commit()
        await engine.dispose()
        return stats


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--account", required=True, help="Smart Mail account e-mail (mailbox login)")
    p.add_argument("--vcard", type=Path, help="Roundcube vCard export (.vcf)")
    p.add_argument("--identities", type=Path, help="JSON dump of Roundcube identities (fixture)")
    p.add_argument("--responses", type=Path, help="JSON dump of Roundcube responses (fixture)")
    p.add_argument("--roundcube-dsn", help="Optional read-only Roundcube DB DSN (SELECT only)")
    p.add_argument("--roundcube-user-email", help="Roundcube users.username for DSN reads")
    p.add_argument("--dry-run", action="store_true", default=False, help="Print plan only (default unless --apply)")
    p.add_argument("--apply", action="store_true", help="Write into Smart Mail DATABASE_URL")
    p.add_argument("--database-url", default=None, help="Override DATABASE_URL for --apply")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.apply:
        args.dry_run = True
    if args.apply:
        args.dry_run = False

    identities: list[IdentityRow] = []
    responses: list[ResponseRow] = []
    vcard_names: list[str] = []

    if args.vcard:
        if not args.vcard.is_file():
            raise SystemExit(f"vcard not found: {args.vcard}")
        vcard_names = load_vcard_summary(args.vcard)

    if args.identities:
        identities.extend(load_identities_json(args.identities))
    if args.responses:
        responses.extend(load_responses_json(args.responses))

    if args.roundcube_dsn:
        user = args.roundcube_user_email or args.account
        identities.extend(load_identities_from_roundcube_dsn(args.roundcube_dsn, user))
        responses.extend(load_responses_from_roundcube_dsn(args.roundcube_dsn, user))

    if not vcard_names and not identities and not responses:
        raise SystemExit("nothing to import — pass --vcard and/or --identities/--responses (or --roundcube-dsn)")

    print_plan(account=args.account, vcard_names=vcard_names, identities=identities, responses=responses)

    if args.dry_run:
        print("Dry-run only — no writes. Re-run with --apply to import into Smart Mail.")
        return 0

    import os

    db_url = args.database_url or os.environ.get("DATABASE_URL")
    if not db_url:
        raise SystemExit("--apply requires DATABASE_URL or --database-url")
    vcard_text = args.vcard.read_text(encoding="utf-8", errors="replace") if args.vcard else None
    stats = asyncio.run(
        apply_import(
            database_url=db_url,
            account_email=args.account,
            vcard_text=vcard_text,
            identities=identities,
            responses=responses,
        )
    )
    print("Applied:", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
