"""GitHub #23 — Sent folder choice (known folder, \\Sent, NAMESPACE prefix) and sync scope."""

from __future__ import annotations

from app.mail.folders import ListedFolder
from app.mail.imap_append import ensure_sent_folder
from app.mail.sent_folder import choose_sent_folder, sent_create_name
from app.mail.sync import folder_selected


def _folder(name: str, *flags: str, delimiter: str = "/") -> ListedFolder:
    return ListedFolder(name, delimiter, frozenset(flags))


def test_23_create_name_without_prefix() -> None:
    assert sent_create_name("", "/") == "Sent"
    assert sent_create_name("", ".") == "Sent"


def test_23_create_name_with_inbox_prefix() -> None:
    assert sent_create_name("INBOX.", ".") == "INBOX.Sent"
    assert sent_create_name("INBOX", ".") == "INBOX.Sent"
    # imap-test uses separator "/" (dots are rejected in mailbox names).
    assert sent_create_name("INBOX/", "/") == "INBOX/Sent"


def test_23_known_sent_folder_wins_over_special_use() -> None:
    listed = (
        _folder("Sent", "\\Sent"),
        _folder("INBOX.Sent", delimiter="."),
    )
    folder, create = choose_sent_folder(listed, known="INBOX.Sent", prefix="INBOX.", delimiter=".")
    assert (folder, create) == ("INBOX.Sent", False)


def test_23_special_use_sent_when_nothing_is_known() -> None:
    listed = (_folder("INBOX.Odoslané", "\\Sent", delimiter="."),)
    folder, create = choose_sent_folder(listed, known=None, prefix="", delimiter="/")
    assert (folder, create) == ("INBOX.Odoslané", False)


def test_23_leaf_name_matches_prefixed_sent_without_flag() -> None:
    listed = (_folder("INBOX.Sent", delimiter="."), _folder("INBOX", delimiter="."))
    folder, create = choose_sent_folder(listed, known=None, prefix="INBOX.", delimiter=".")
    assert (folder, create) == ("INBOX.Sent", False)


def test_23_creates_only_when_no_sent_folder_exists() -> None:
    listed = (_folder("INBOX", delimiter="."),)
    folder, create = choose_sent_folder(listed, known=None, prefix="INBOX.", delimiter=".")
    assert (folder, create) == ("INBOX.Sent", True)
    plain, plain_create = choose_sent_folder(listed, known=None, prefix="", delimiter="/")
    assert (plain, plain_create) == ("Sent", True)


class _FakeImap:
    def __init__(self, folders: list[tuple[object, object, object]], namespace: object) -> None:
        self._folders = folders
        self._namespace = namespace
        self.created: list[str] = []
        self.subscribed: list[str] = []

    def list_folders(self) -> list[tuple[object, object, object]]:
        return list(self._folders)

    def namespace(self) -> object:
        return self._namespace

    def create_folder(self, name: str) -> None:
        self.created.append(name)

    def subscribe_folder(self, name: str) -> None:
        self.subscribed.append(name)


def test_23_ensure_creates_sent_for_both_namespaces() -> None:
    plain = _FakeImap([], ((("", "/"),), None, None))
    assert ensure_sent_folder(plain, known=None) == "Sent"  # type: ignore[arg-type]
    assert plain.created == ["Sent"]
    assert plain.subscribed == ["Sent"]

    prefixed = _FakeImap([], ((("INBOX.", "."),), None, None))
    assert ensure_sent_folder(prefixed, known=None) == "INBOX.Sent"  # type: ignore[arg-type]
    assert prefixed.created == ["INBOX.Sent"]
    assert prefixed.subscribed == ["INBOX.Sent"]


def test_23_ensure_reuses_existing_sent_and_does_not_create() -> None:
    client = _FakeImap([(b"\\Sent", b"/", "Sent")], ((("INBOX.", "."),), None, None))
    assert ensure_sent_folder(client, known=None) == "Sent"  # type: ignore[arg-type]
    assert client.created == []


def test_23_explicit_folder_sync_includes_unsubscribed_names() -> None:
    assert folder_selected(
        name="INBOX.Sent",
        is_inbox=False,
        subscribed=set(),
        scope="others",
        only_names=frozenset({"INBOX.Sent"}),
    )
    assert not folder_selected(
        name="INBOX",
        is_inbox=True,
        subscribed=set(),
        scope="all",
        only_names=frozenset({"INBOX.Sent"}),
    )
    assert not folder_selected(
        name="INBOX.Sent",
        is_inbox=False,
        subscribed=set(),
        scope="others",
        only_names=None,
    )
