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
    "INBOX": ["Kópia faktúry {n}", "Cenová ponuka M10×30 A2", "Objednávka PO-{n}", "Reklamácia – podložky M12",
              "Dodacia lehota – kotvy", "Dopyt: skrutky DIN 933 M8×25", "Otázka k dodávke {n}"],
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
# (folder, number of messages, number unread)
PILOT_PLAN = [
    ("INBOX", 42, 12), ("Drafts", 2, 0), ("Sent", 12, 0), ("Junk", 3, 3), ("Trash", 5, 0),
    ("Archív", 6, 0), ("Dodávatelia", 9, 2), ("Faktúry", 15, 4), ("Kurier", 8, 1), ("Nitra", 5, 2),
    ("Senica", 6, 3), ("Smart", 4, 0), ("Trenčín", 7, 1),
]
# pilot gets about 30 % of 50 MB through a few larger fictional price lists
PILOT_FILLER_KB = 15_000


def read_users() -> dict[str, str]:
    users: dict[str, str] = {}
    for line in USERS_FILE.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        user, password = line.split(":")[0:2]
        users[user] = password.removeprefix("{PLAIN}")
    return users


def message(rng: random.Random, folder: str, index: int, to: str, *, attachment_kb: int = 0) -> tuple[bytes, datetime]:
    name, addr, company = rng.choice(SENDERS)
    number = rng.randint(1000, 9999)
    subject = rng.choice(SUBJECTS.get(folder, SUBJECTS["INBOX"])).format(n=f"2026{number}")
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
    msg["Message-ID"] = make_msgid(domain=DOMAIN)
    msg.set_content(
        f"Dobrý deň,\n\ntoto je fiktívna testovacia správa č. {index + 1} pre priečinok {folder}.\n"
        f"Firma: {company}\n\nS pozdravom\n{name}\n"
    )
    if attachment_kb:
        payload = rng.randbytes(attachment_kb * 1024)
        msg.add_attachment(payload, maintype="application", subtype="pdf", filename=f"cennik-{number}.pdf")
    return msg.as_bytes(), sent


def wipe(client: IMAPClient) -> None:
    for _flags, _delim, name in client.list_folders():
        client.select_folder(name)
        uids = client.search("ALL")
        if uids:
            client.delete_messages(uids)
            client.expunge()
        client.close_folder()
        if name in OWN_FOLDERS:
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
            raw, sent = message(rng, folder, i, user)
            append(client, folder, raw, sent, seen=i >= unread, flagged=folder == "INBOX" and i in (3, 9, 17))
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
    ensure_folders(client)
    for i in range(15):
        raw, sent = message(rng, "INBOX", i, user)
        append(client, "INBOX", raw, sent, seen=i >= 5)


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
    args = parser.parse_args(argv)
    if args.host not in ALLOWED_HOSTS:
        print(f"refusing to seed {args.host}: only the local test server ({', '.join(sorted(ALLOWED_HOSTS))})")
        return 2
    users = read_users()
    for user, seeder in SEEDERS.items():
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
            seeder(client, user, random.Random(f"smartmail-1c-{user}"))
            used, limit = quota(client)
            print(f"{user}: seeded, quota {used} / {limit} KB ({used * 100 // limit} %)")
        finally:
            client.logout()
    return 0


if __name__ == "__main__":
    sys.exit(main())
