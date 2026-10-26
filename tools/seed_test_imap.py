"""Fill the local TEST IMAP server (infra/imap-test, Dovecot) with fictional mail for development and tests.

Never point this at a real server: it refuses any host except localhost / the compose service and any address outside
the fictional domain smartmail.test.

    uv run python tools/seed_test_imap.py                       # compose: localhost:1143
    uv run python tools/seed_test_imap.py --port 143 --reset    # local Dovecot, wipe and seed again

Mailboxes (infra/imap-test/users):
- pilot@smartmail.test   the customer's Roundcube folders with fictional mail, quota about 30 %
- plna@smartmail.test    quota above 90 % (red quota bar, SCREENS_SPEC G3)
- senica@smartmail.test  branch mailbox for the "Kto ste?" picker
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from pathlib import Path

from imapclient import IMAPClient

ALLOWED_HOSTS = {"localhost", "127.0.0.1", "imap-test"}
DOMAIN = "smartmail.test"
USERS_FILE = Path(__file__).resolve().parent.parent / "infra" / "imap-test" / "users"

# The customer's own folders (DECISIONS D21) next to the special-use folders Dovecot creates (Drafts, Sent, Junk, Trash).
OWN_FOLDERS = ["Archív", "Dodávatelia", "Faktúry", "Kurier", "Nitra", "Senica", "Smart", "Trenčín"]

SENDERS = [
    ("Ján Novák", "novak@abcstav.example", "ABC Stav s.r.o."),
    ("Peter Hudec", "hudec@kovotrnava.example", "Kovo Trnava s.r.o."),
    ("Martin Kráľ", "kral@stavmont.example", "Stavmont a.s."),
    ("Lucia Beňová", "benova@elektrobeno.example", "Elektro Beňo s.r.o."),
    ("Klaus Weber", "weber@schrauben-weber.example", "Schrauben Weber GmbH"),
    ("Eva Malá", "mala@hrubystavby.example", "Hrubý Stavby s.r.o."),
    ("Kuriér Express", "noreply@kurier-express.example", "Kuriér Express"),
    ("Fakturácia", "fakturacia@fixtech.example", "Fixtech CZ s.r.o."),
]
SUBJECTS = {
    "INBOX": [
        "Kópia faktúry {n}",
        "Cenová ponuka M10×30 A2",
        "Objednávka PO-{n}",
        "Reklamácia – podložky M12",
        "Dodacia lehota – kotvy",
        "Dopyt: skrutky DIN 933 M8×25",
        "Otázka k dodávke {n}",
        # long subjects for list truncation screenshots (Phase 1e)
        "Prosím o zaslanie aktuálneho cenníka skrutiek DIN 933 M6–M16 vrátane dodacích lehôt a množstevných zliav {n}",
        "Urgentná reklamácia – dodávka {n}: chýbajúce podložky M12 a nesprávny materiál A2 namiesto A4",
    ],
    "Dodávatelia": ["Nový cenník {n}", "Potvrdenie objednávky {n}", "Dodací list {n}"],
    "Faktúry": ["Faktúra {n}", "Faktúra FV{n}", "Dobropis {n}"],
    "Kurier": ["Zásielka {n} doručená", "Zásielka {n} na ceste", "Zásielka {n} – nedoručená"],
    "Nitra": ["Nitra: objednávka {n}", "Nitra: dopyt na kotvy"],
    "Senica": ["Senica: objednávka {n}", "Senica: vrátenie tovaru"],
    "Trenčín": ["Trenčín: objednávka {n}", "Trenčín: otázka k faktúre {n}"],
    "Smart": ["Porada v piatok", "Dovolenky – plán", "Inventúra {n}"],
    "Archív": ["Zmluva {n}", "Archív: ponuka {n}"],
    "Sent": ["Re: Objednávka PO-{n}", "Ponuka {n}", "Re: Reklamácia {n}"],
    "Drafts": ["Koncept: odpoveď na dopyt", "Koncept: ponuka {n}"],
    "Junk": ["Výhra! Kliknite sem", "Lacné hodinky"],
    "Trash": ["Staré oznámenie {n}", "Newsletter {n}"],
}
# (folder, number of messages, number unread) — pilot ≥ 60 across Roundcube folders for W2 screenshots
PILOT_PLAN = [
    ("INBOX", 48, 14),
    ("Drafts", 3, 0),
    ("Sent", 14, 0),
    ("Junk", 4, 4),
    ("Trash", 5, 0),
    ("Archív", 6, 0),
    ("Dodávatelia", 10, 3),
    ("Faktúry", 16, 5),
    ("Kurier", 8, 2),
    ("Nitra", 6, 2),
    ("Senica", 8, 3),
    ("Smart", 4, 0),
    ("Trenčín", 8, 2),
]
# pilot gets about 30 % of 50 MB through a few larger fictional price lists
PILOT_FILLER_KB = 15_000
# small PDFs on some ordinary messages (list “S prílohou” looks realistic without filling quota)
SMALL_ATTACHMENT_KB = 12


def read_users() -> dict[str, str]:
    users: dict[str, str] = {}
    for line in USERS_FILE.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        user, password = line.split(":")[0:2]
        users[user] = password.removeprefix("{PLAIN}")
    return users


def message(
    rng: random.Random,
    folder: str,
    index: int,
    to: str,
    *,
    attachment_kb: int = 0,
    subject: str | None = None,
    message_id: str | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> tuple[bytes, datetime]:
    name, addr, company = rng.choice(SENDERS)
    number = rng.randint(1000, 9999)
    subject = subject or rng.choice(SUBJECTS.get(folder, SUBJECTS["INBOX"])).format(n=f"2026{number}")
    sent = datetime(2026, 10, 26, 9, 0, tzinfo=UTC) - timedelta(hours=index * 7 + rng.randint(0, 6))
    msg = EmailMessage()
    if folder in ("Sent", "Drafts"):
        msg["From"] = to
        msg["To"] = f"{name} <{addr}>"
    else:
        msg["From"] = f"{name} <{addr}>"
        msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = format_datetime(sent)
    mid = message_id or make_msgid(domain=DOMAIN)
    msg["Message-ID"] = mid
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    msg.set_content(
        f"Dobrý deň,\n\ntoto je fiktívna testovacia správa č. {index + 1} pre priečinok {folder}.\n"
        f"Firma: {company}\n\nS pozdravom\n{name}\n"
    )
    if attachment_kb:
        payload = rng.randbytes(attachment_kb * 1024)
        msg.add_attachment(payload, maintype="application", subtype="pdf", filename=f"cennik-{number}.pdf")
    return msg.as_bytes(), sent


def wipe(client: IMAPClient) -> None:
    """Empty every folder and delete all but INBOX and the SPECIAL-USE ones (also folders left over by tests)."""
    folders = client.list_folders()
    for _flags, _delim, name in folders:
        client.select_folder(name)
        uids = client.search("ALL")
        if uids:
            client.delete_messages(uids)
            client.expunge()
        client.close_folder()
    special = {b"\\Drafts", b"\\Sent", b"\\Junk", b"\\Trash"}
    own = [name for flags, _d, name in folders if name.upper() != "INBOX" and not special & set(flags)]
    for name in sorted(own, key=len, reverse=True):  # children before parents
        client.unsubscribe_folder(name)
        client.delete_folder(name)


def ensure_folders(client: IMAPClient) -> None:
    existing = {name for _flags, _delim, name in client.list_folders()}
    for folder in OWN_FOLDERS:
        if folder not in existing:
            client.create_folder(folder)
        client.subscribe_folder(folder)


def append(client: IMAPClient, folder: str, raw: bytes, sent: datetime, seen: bool, flagged: bool = False) -> None:
    flags: list[bytes] = []
    if seen:
        flags.append(b"\\Seen")
    if flagged:
        flags.append(b"\\Flagged")
    client.append(folder, raw, flags=flags, msg_time=sent)


def quota(client: IMAPClient) -> tuple[int, int]:
    _roots, quotas = client.get_quota_root("INBOX")
    storage = next(q for q in quotas if q.resource.upper() == "STORAGE")
    return int(storage.usage), int(storage.limit)


def seed_pilot(client: IMAPClient, user: str, rng: random.Random) -> None:
    ensure_folders(client)
    for folder, count, unread in PILOT_PLAN:
        for i in range(count):
            attach = SMALL_ATTACHMENT_KB if folder == "INBOX" and i in (0, 5, 11, 22, 33) else 0
            raw, sent = message(rng, folder, i, user, attachment_kb=attach)
            append(client, folder, raw, sent, seen=i >= unread, flagged=folder == "INBOX" and i in (3, 9, 17))
    # three short threads in INBOX (parent + reply) for Konverzácie screenshots
    for t in range(3):
        parent_id = make_msgid(domain="dodavatel.example")
        subj = f"Vlákno dodávky DL-seed-{t + 1} – potvrdenie množstva a termínu"
        raw_p, sent_p = message(
            rng, "INBOX", 80 + t, user, subject=subj, message_id=parent_id, attachment_kb=SMALL_ATTACHMENT_KB
        )
        append(client, "INBOX", raw_p, sent_p, seen=False)
        raw_r, sent_r = message(
            rng,
            "INBOX",
            90 + t,
            user,
            subject=f"Re: {subj}",
            in_reply_to=parent_id,
            references=parent_id,
        )
        append(client, "INBOX", raw_r, sent_r, seen=True)
    for i in range(3):
        raw, sent = message(rng, "Dodávatelia", 20 + i, user, attachment_kb=PILOT_FILLER_KB // 3)
        append(client, "Dodávatelia", raw, sent, seen=True)


def seed_full(client: IMAPClient, user: str, rng: random.Random) -> None:
    """Fill to 92–96 % of the quota (SCREENS_SPEC G3: red bar from 90 %)."""
    ensure_folders(client)
    for i in range(6):
        raw, sent = message(rng, "INBOX", i, user)
        append(client, "INBOX", raw, sent, seen=i >= 2)
    i = 6
    while True:
        used, limit = quota(client)
        if used >= limit * 0.92:
            break
        room_kb = int(limit * 0.94) - used
        raw, sent = message(rng, "INBOX", i, user, attachment_kb=max(1, min(300, int(room_kb * 0.7))))
        append(client, "INBOX", raw, sent, seen=True)
        i += 1


def seed_branch(client: IMAPClient, user: str, rng: random.Random) -> None:
    """Branch mailbox ≥ 60 fictional messages across folders (Phase 1e list screenshots)."""
    ensure_folders(client)
    plan = [
        ("INBOX", 28, 9),
        ("Drafts", 2, 0),
        ("Sent", 8, 0),
        ("Junk", 2, 2),
        ("Trash", 3, 0),
        ("Dodávatelia", 6, 2),
        ("Faktúry", 7, 2),
        ("Kurier", 4, 1),
    ]
    for folder, count, unread in plan:
        for i in range(count):
            attach = SMALL_ATTACHMENT_KB if folder == "INBOX" and i % 7 == 0 else 0
            raw, sent = message(rng, folder, i, user, attachment_kb=attach)
            append(client, folder, raw, sent, seen=i >= unread, flagged=folder == "INBOX" and i in (2, 8))
    parent_id = make_msgid(domain="dodavatel.example")
    raw_p, sent_p = message(
        rng,
        "INBOX",
        40,
        user,
        subject="Senica: vlákno objednávky PO-seed-1 – dlhý predmet pre skrátenie v zozname",
        message_id=parent_id,
        attachment_kb=SMALL_ATTACHMENT_KB,
    )
    append(client, "INBOX", raw_p, sent_p, seen=False)
    raw_r, sent_r = message(
        rng,
        "INBOX",
        41,
        user,
        subject="Re: Senica: vlákno objednávky PO-seed-1 – dlhý predmet pre skrátenie v zozname",
        in_reply_to=parent_id,
        references=parent_id,
    )
    append(client, "INBOX", raw_r, sent_r, seen=True)


SEEDERS = {
    f"pilot@{DOMAIN}": seed_pilot,
    f"plna@{DOMAIN}": seed_full,
    f"senica@{DOMAIN}": seed_branch,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=1143)
    parser.add_argument("--reset", action="store_true", help="delete all messages and own folders first")
    parser.add_argument("--user", action="append", help="seed only this test user (repeatable)")
    args = parser.parse_args(argv)
    if args.host not in ALLOWED_HOSTS:
        print(f"refusing to seed {args.host}: only the local test server ({', '.join(sorted(ALLOWED_HOSTS))})")
        return 2
    users = read_users()
    for user, seeder in SEEDERS.items():
        if args.user and user not in args.user:
            continue
        if not user.endswith(f"@{DOMAIN}"):
            return 2
        client = IMAPClient(args.host, port=args.port, ssl=False, timeout=30)
        try:
            client.login(user, users[user])
            if args.reset:
                wipe(client)
            client.select_folder("INBOX")
            if client.search("ALL") and not args.reset:
                print(f"{user}: already seeded (use --reset)")
                continue
            client.close_folder()
            seeder(client, user, random.Random(f"smartmail-1c-{user}"))  # noqa: S311 - deterministic fixtures
            used, limit = quota(client)
            print(f"{user}: seeded, quota {used} / {limit} KB ({used * 100 // limit} %)")
        finally:
            client.logout()
    return 0


if __name__ == "__main__":
    sys.exit(main())
