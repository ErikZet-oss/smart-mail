#!/usr/bin/env python3
"""Minimal SMTP submission with mandatory AUTH → local Dovecot LMTP.

Dovecot's submission service requires submission_relay_host; for the TEST image we
instead expose this bridge on :587 so CI can prove mailbox SMTP AUTH (GitHub #20).
Unauthenticated MAIL FROM is rejected. Credentials match /etc/dovecot/users.
"""

from __future__ import annotations

import asyncio
import re
import smtplib

USERS_PATH = "/etc/dovecot/users"
LMTP_HOST = "127.0.0.1"
LMTP_PORT = 24
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 587

_USER_RE = re.compile(r"^([^:]+):\{PLAIN\}([^:]+):")
# MAIL FROM:<a@b> BODY=8BITMIME  /  RCPT TO:<a@b>
_PATH_RE = re.compile(r"<?([^<>\s]+@[^<>\s]+)>?")


def _addr_from_smtp_path(raw: str) -> str:
    """Extract the mailbox from an SMTP reverse-path / forward-path (ignore ESMTP params)."""
    m = _PATH_RE.search(raw.strip())
    return m.group(1).lower() if m else raw.strip().strip("<>").split()[0].lower()


def load_users(path: str = USERS_PATH) -> dict[str, str]:
    out: dict[str, str] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = _USER_RE.match(line)
            if m:
                out[m.group(1).lower()] = m.group(2)
    return out


class Session:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, users: dict[str, str]) -> None:
        self.reader = reader
        self.writer = writer
        self.users = users
        self.peer = writer.get_extra_info("peername")
        self.authed: str | None = None
        self.mail_from: str | None = None
        self.rcpt: list[str] = []
        self.data_mode = False
        self.buf = bytearray()

    async def send(self, line: str) -> None:
        self.writer.write((line + "\r\n").encode("ascii", errors="replace"))
        await self.writer.drain()

    async def run(self) -> None:
        await self.send("220 smartmail.test ESMTP AUTH required")
        try:
            while True:
                line = await self.reader.readline()
                if not line:
                    break
                if self.data_mode:
                    if line == b".\r\n" or line == b".\n":
                        await self._deliver()
                        self.data_mode = False
                        self.buf.clear()
                        self.mail_from = None
                        self.rcpt.clear()
                    else:
                        # RFC 5321 dot-stuffing
                        if line.startswith(b"."):
                            line = line[1:]
                        self.buf.extend(line)
                    continue
                text = line.decode("utf-8", errors="replace").rstrip("\r\n")
                await self._command(text)
        finally:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except OSError:
                pass

    async def _command(self, text: str) -> None:
        upper = text.upper()
        if upper.startswith("EHLO") or upper.startswith("HELO"):
            await self.send("250-smartmail.test")
            await self.send("250-AUTH PLAIN LOGIN")
            await self.send("250-8BITMIME")
            await self.send("250 OK")
        elif upper.startswith("AUTH PLAIN"):
            parts = text.split(" ", 2)
            if len(parts) == 3:
                await self._auth_plain(parts[2].strip())
            else:
                await self.send("334 ")
                secret = (await self.reader.readline()).decode("ascii", errors="replace").strip()
                await self._auth_plain(secret)
        elif upper.startswith("AUTH LOGIN"):
            await self.send("334 VXNlcm5hbWU6")  # Username:
            user_b64 = (await self.reader.readline()).decode("ascii", errors="replace").strip()
            await self.send("334 UGFzc3dvcmQ6")  # Password:
            pass_b64 = (await self.reader.readline()).decode("ascii", errors="replace").strip()
            import base64

            try:
                user = base64.b64decode(user_b64).decode("utf-8")
                password = base64.b64decode(pass_b64).decode("utf-8")
            except (ValueError, UnicodeError):
                await self.send("535 5.7.8 Authentication failed")
                return
            if self.users.get(user.lower()) == password:
                self.authed = user.lower()
                await self.send("235 2.7.0 Authentication successful")
            else:
                await self.send("535 5.7.8 Authentication failed")
        elif upper.startswith("MAIL FROM:"):
            if not self.authed:
                await self.send("530 5.7.0 Authentication required")
                return
            self.mail_from = _addr_from_smtp_path(text[10:])
            await self.send("250 2.1.0 OK")
        elif upper.startswith("RCPT TO:"):
            if not self.authed:
                await self.send("530 5.7.0 Authentication required")
                return
            self.rcpt.append(_addr_from_smtp_path(text[8:]))
            await self.send("250 2.1.5 OK")
        elif upper == "DATA":
            if not self.authed or not self.mail_from or not self.rcpt:
                await self.send("503 5.5.1 Bad sequence")
                return
            await self.send("354 End data with <CR><LF>.<CR><LF>")
            self.data_mode = True
            self.buf.clear()
        elif upper == "RSET":
            self.mail_from = None
            self.rcpt.clear()
            await self.send("250 OK")
        elif upper == "NOOP":
            await self.send("250 OK")
        elif upper == "QUIT":
            await self.send("221 Bye")
            self.writer.close()
        else:
            await self.send("502 5.5.1 Command not implemented")

    async def _auth_plain(self, secret: str) -> None:
        import base64

        try:
            raw = base64.b64decode(secret)
            # authzid \0 authcid \0 password
            parts = raw.split(b"\0")
            if len(parts) == 3:
                user = parts[1].decode("utf-8")
                password = parts[2].decode("utf-8")
            elif len(parts) == 2:
                user = parts[0].decode("utf-8")
                password = parts[1].decode("utf-8")
            else:
                await self.send("535 5.7.8 Authentication failed")
                return
        except (ValueError, UnicodeError):
            await self.send("535 5.7.8 Authentication failed")
            return
        if self.users.get(user.lower()) == password:
            self.authed = user.lower()
            await self.send("235 2.7.0 Authentication successful")
        else:
            await self.send("535 5.7.8 Authentication failed")

    async def _deliver(self) -> None:
        assert self.mail_from and self.rcpt
        raw = bytes(self.buf)
        if b"\n\n" not in raw and b"\r\n\r\n" not in raw:
            raw = b"Subject: (no subject)\r\n\r\n" + raw
        try:
            await asyncio.to_thread(self._lmtp, self.mail_from, list(self.rcpt), raw)
            await self.send("250 2.0.0 OK queued")
        except Exception as exc:
            # stderr goes to docker logs — never include body
            import sys

            print(f"lmtp.delivery_failed type={type(exc).__name__} detail={exc!s}", file=sys.stderr, flush=True)
            await self.send("451 4.3.0 Temporary delivery failure")

    def _lmtp(self, mail_from: str, rcpt: list[str], raw: bytes) -> None:
        # Strip display-name wrappers: "Pilot <pilot@…>" → pilot@…
        mail_from = mail_from.strip().strip("<>")
        if "<" in mail_from and ">" in mail_from:
            mail_from = mail_from[mail_from.rfind("<") + 1 : mail_from.rfind(">")]
        cleaned = []
        for addr in rcpt:
            addr = addr.strip().strip("<>")
            if "<" in addr and ">" in addr:
                addr = addr[addr.rfind("<") + 1 : addr.rfind(">")]
            cleaned.append(addr)
        with smtplib.LMTP(LMTP_HOST, LMTP_PORT, timeout=10) as client:
            # Issue MAIL/RCPT/DATA manually — smtplib.sendmail auto-adds BODY=8BITMIME which
            # Dovecot LMTP rejects with 555 Unsupported mail BODY type.
            code, _resp = client.mail(mail_from, options=[])
            if code >= 400:
                raise smtplib.SMTPSenderRefused(code, _resp, mail_from)
            for addr in cleaned:
                code, _resp = client.rcpt(addr, options=[])
                if code >= 400:
                    raise smtplib.SMTPRecipientsRefused({addr: (code, _resp)})
            code, _resp = client.data(raw)
            if code >= 400:
                raise smtplib.SMTPDataError(code, _resp)


async def main() -> None:
    users = load_users()
    if not users:
        raise SystemExit("no users in " + USERS_PATH)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await Session(reader, writer, users).run()

    server = await asyncio.start_server(handle, LISTEN_HOST, LISTEN_PORT)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
