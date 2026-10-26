"""IMAP IDLE on INBOX (CLAUDE.md §5: re-IDLE every 25 minutes). One thread per mailbox in the worker; every
server push (EXISTS, EXPUNGE, FETCH) asks the worker to sync INBOX. Other folders are polled every 2 minutes."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import structlog
from imapclient.exceptions import IMAPClientError

from app.mail.imap import ImapServer
from app.mail.sync import Credentials, SyncAuthError, SyncUnavailable, connect, logout_quietly

log = structlog.get_logger(__name__)

CHECK_EVERY_S = 30
MAX_BACKOFF_S = 300
PUSH_RESPONSES = frozenset({b"EXISTS", b"EXPUNGE", b"FETCH", b"RECENT", b"VANISHED"})


class InboxWatcher:
    def __init__(
        self,
        mailbox_id: str,
        server: ImapServer,
        creds: Credentials,
        *,
        on_change: Callable[[], None],
        on_auth_failed: Callable[[], None],
        renew_s: int,
        check_every_s: int = CHECK_EVERY_S,
    ) -> None:
        self.mailbox_id = mailbox_id
        self.server = server
        self.creds = creds
        self.on_change = on_change
        self.on_auth_failed = on_auth_failed
        self.renew_s = renew_s
        self.check_every_s = check_every_s
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name=f"idle-{mailbox_id}", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    @property
    def alive(self) -> bool:
        return self.thread.is_alive()

    def _run(self) -> None:
        backoff = 5
        while not self.stop_event.is_set():
            try:
                self._session()
                backoff = 5
            except SyncAuthError:
                log.warning("mail.idle_auth_failed", mailbox_id=self.mailbox_id)
                self.on_auth_failed()
                return
            except (SyncUnavailable, OSError, IMAPClientError) as exc:
                log.warning("mail.idle_disconnected", mailbox_id=self.mailbox_id, error=type(exc).__name__)
                self.stop_event.wait(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_S)

    def _session(self) -> None:
        client = connect(self.server, self.creds)
        try:
            if not client.has_capability("IDLE"):
                log.info("mail.idle_unsupported", mailbox_id=self.mailbox_id)
                self.stop_event.wait(self.renew_s)  # the poll covers INBOX too while IDLE is missing
                return
            client.select_folder("INBOX", readonly=True)
            self.on_change()  # catch up with anything that arrived while not connected
            while not self.stop_event.is_set():
                client.idle()
                started = time.monotonic()
                changed = False
                try:
                    while not self.stop_event.is_set() and time.monotonic() - started < self.renew_s:
                        responses = client.idle_check(timeout=self.check_every_s)
                        if any(len(r) > 1 and r[1] in PUSH_RESPONSES for r in responses):
                            changed = True
                            break
                finally:
                    client.idle_done()
                if changed:
                    self.on_change()
        finally:
            logout_quietly(client)
