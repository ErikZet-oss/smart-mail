"""ImapAuthenticator against a minimal local IMAP stub (no real mail server, no credentials)."""

from __future__ import annotations

import socket
import socketserver
import threading
from collections.abc import Iterator

import pytest

from app.mail.imap import ImapAuthenticator, ImapServer, LoginResult

USER, PASSWORD = "jana@smartsro.sk", "Spravne-Heslo-1"


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        self.wfile.write(b"* OK [CAPABILITY IMAP4rev1 AUTH=PLAIN] stub ready\r\n")
        for raw in self.rfile:
            parts = raw.decode().strip().split(" ", 3)
            tag, cmd = parts[0], parts[1].upper() if len(parts) > 1 else ""
            if cmd == "CAPABILITY":
                self.wfile.write(b"* CAPABILITY IMAP4rev1 AUTH=PLAIN\r\n" + f"{tag} OK done\r\n".encode())
            elif cmd == "LOGIN":
                user, pw = (p.strip('"') for p in parts[2:4])
                ok = user == USER and pw == PASSWORD
                line = f"{tag} OK logged in\r\n" if ok else f"{tag} NO [AUTHENTICATIONFAILED] bad\r\n"
                self.wfile.write(line.encode())
            elif cmd == "LOGOUT":
                self.wfile.write(b"* BYE\r\n" + f"{tag} OK bye\r\n".encode())
                return
            else:
                self.wfile.write(f"{tag} BAD unknown\r\n".encode())


@pytest.fixture
def stub_port() -> Iterator[int]:
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


def _auth(port: int) -> ImapAuthenticator:
    return ImapAuthenticator(ImapServer("127.0.0.1", port, "none", 3))


async def test_imap_login_ok(stub_port: int) -> None:
    assert await _auth(stub_port).verify(USER, PASSWORD) is LoginResult.ok


async def test_imap_login_wrong_password(stub_port: int) -> None:
    assert await _auth(stub_port).verify(USER, "zle") is LoginResult.invalid_credentials


async def test_imap_server_unreachable() -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]
    assert await _auth(free_port).verify(USER, PASSWORD) is LoginResult.server_unavailable
