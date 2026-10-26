"""Phase 1c folder rules: SPECIAL-USE mapping, Roundcube order, quota level, folder name checks (SCREENS_SPEC G3,
UX_SPEC W2 folder column, PRODUCT_SPEC §1 parity rows "Folders" and "Quota")."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.mail.folders import (
    FolderNameError,
    ListedFolder,
    QuotaLevel,
    assign_special_use,
    child_name,
    order_folders,
    quota_view,
    rename_target,
    validate_folder_name,
)


def lf(name: str, *flags: str, delimiter: str = "/") -> ListedFolder:
    return ListedFolder(name=name, delimiter=delimiter, flags=frozenset(flags))


def test_g3_special_use_from_imap_flags() -> None:
    folders = [
        lf("INBOX"),
        lf("Drafts", "\\Drafts"),
        lf("Sent", "\\Sent"),
        lf("Junk", "\\Junk"),
        lf("Trash", "\\Trash"),
        lf("Archív"),
    ]
    assert assign_special_use(folders) == {
        "INBOX": "inbox",
        "Drafts": "drafts",
        "Sent": "sent",
        "Junk": "junk",
        "Trash": "trash",
    }


def test_g3_archive_is_an_own_folder_even_with_the_archive_flag() -> None:
    # UX_SPEC §5 icons: "vlastný priečinok (aj Archív)"
    assert "Archive" not in assign_special_use([lf("INBOX"), lf("Archive", "\\Archive")])


def test_g3_special_use_falls_back_to_roundcube_names_without_special_use() -> None:
    folders = [lf("INBOX"), lf("Koncepty"), lf("Odoslané"), lf("Spam"), lf("Kôš"), lf("Nitra")]
    assert assign_special_use(folders) == {
        "INBOX": "inbox",
        "Koncepty": "drafts",
        "Odoslané": "sent",
        "Spam": "junk",
        "Kôš": "trash",
    }


def test_g3_flagged_folder_wins_over_name_fallback() -> None:
    folders = [lf("INBOX"), lf("Trash"), lf("Deleted Items", "\\Trash")]
    assert assign_special_use(folders)["Deleted Items"] == "trash"
    assert "Trash" not in assign_special_use(folders)


def test_g3_inbox_is_case_insensitive_and_never_a_subfolder() -> None:
    assert assign_special_use([lf("inbox"), lf("Nitra/INBOX")]) == {"inbox": "inbox"}


def test_g3_order_special_folders_then_own_folders_sorted_slovak() -> None:
    names = ["Trenčín", "Kurier", "Kôš", "Senica", "INBOX", "Archív", "Odoslané", "Faktúry", "Nevyžiadaná pošta"]
    names += ["Koncepty", "Dodávatelia", "Smart", "Nitra", "Čakajúce"]
    special = {"INBOX": "inbox", "Koncepty": "drafts", "Odoslané": "sent", "Nevyžiadaná pošta": "junk", "Kôš": "trash"}
    ordered = order_folders([(n, "/") for n in names], special)
    assert [f.name for f in ordered] == [
        "INBOX",
        "Koncepty",
        "Odoslané",
        "Nevyžiadaná pošta",
        "Kôš",
        "Archív",
        "Čakajúce",  # Slovak alphabet: c < č < d
        "Dodávatelia",
        "Faktúry",
        "Kurier",
        "Nitra",
        "Senica",
        "Smart",
        "Trenčín",
    ]


def test_g3_subfolders_follow_their_parent_with_depth() -> None:
    ordered = order_folders(
        [("INBOX", "/"), ("Nitra/2026", "/"), ("Dodávatelia", "/"), ("Nitra", "/"), ("Nitra/2025", "/")],
        {"INBOX": "inbox"},
    )
    assert [(f.name, f.depth, f.label) for f in ordered] == [
        ("INBOX", 0, "INBOX"),
        ("Dodávatelia", 0, "Dodávatelia"),
        ("Nitra", 0, "Nitra"),
        ("Nitra/2025", 1, "2025"),
        ("Nitra/2026", 1, "2026"),
    ]
    assert ordered[3].parent == "Nitra"


def test_g3_subfolder_of_inbox_is_listed_under_inbox() -> None:
    special = {"INBOX": "inbox", "Kôš": "trash"}
    ordered = order_folders([("INBOX.Objednávky", "."), ("INBOX", "."), ("Kôš", ".")], special)
    assert [f.name for f in ordered] == ["INBOX", "INBOX.Objednávky", "Kôš"]


@pytest.mark.parametrize(
    ("used", "limit", "percent", "level"),
    [
        (0, 1000, 0, QuotaLevel.normal),
        (749, 1000, 74, QuotaLevel.normal),
        (750, 1000, 75, QuotaLevel.warning),
        (899, 1000, 89, QuotaLevel.warning),
        (900, 1000, 90, QuotaLevel.danger),
        (1914, 2048, 93, QuotaLevel.danger),
        (1200, 1000, 100, QuotaLevel.danger),
    ],
)
def test_g3_quota_red_from_90_percent_amber_from_75(used: int, limit: int, percent: int, level: QuotaLevel) -> None:
    view = quota_view(used, limit)
    assert view is not None
    assert (view.percent, view.level) == (percent, level)


def test_g3_quota_hidden_without_a_limit() -> None:
    assert quota_view(None, None) is None
    assert quota_view(10, 0) is None


@pytest.mark.parametrize("name", ["Nitra", "Objednávky 2026", "Dodávatelia – archív"])
def test_g5_valid_folder_names(name: str) -> None:
    assert validate_folder_name(name, "/") == name


@pytest.mark.parametrize("name", ["", "   ", "a/b", "*", "x%", "INBOX", "inbox", "x" * 101, "a\nb", "a\x00"])
def test_g5_invalid_folder_names_are_refused(name: str) -> None:
    with pytest.raises(FolderNameError):
        validate_folder_name(name, "/")


def test_g5_child_and_rename_paths_keep_the_parent() -> None:
    assert child_name("Nitra", "/", "2026") == "Nitra/2026"
    assert child_name(None, "/", "Nové") == "Nové"
    assert rename_target("Nitra/2025", "/", "Staré") == "Nitra/Staré"
    assert rename_target("Kurier", "/", "Kuriér") == "Kuriér"


@given(st.text(max_size=120))
def test_g5_validated_names_never_contain_wildcards_or_the_delimiter(name: str) -> None:
    try:
        clean = validate_folder_name(name, ".")
    except FolderNameError:
        return
    assert not set(clean) & {".", "*", "%", "\\", '"'}
    assert clean == clean.strip() and 0 < len(clean) <= 100
    assert all(ch.isprintable() for ch in clean)
