"""Pilot 2026-11-03: the recipient of a forward did not see who wrote the original. Like Roundcube, the forwarded
quote starts with „-------- Pôvodná správa --------“ and a Predmet / Dátum / Od / Komu table."""

from __future__ import annotations

from datetime import UTC, datetime

from app.mail.compose_html import assemble_outgoing_html, forward_header_html, strip_protected


def _header() -> str:
    return forward_header_html(
        subject="Re: [Smart s.r.o.] Čaká sa na platbu",
        date=datetime(2026, 11, 3, 6, 47, tzinfo=UTC),
        from_name="Kovacs Jozef",
        from_email="jozef@example.test",
        to=[{"name": "Smart s.r.o. Spojovací materiál", "email": "eshop@smartsro.sk"}],
        cc=[{"name": None, "email": "kopia@example.test"}],
    )


def test_forward_header_has_roundcube_rows_in_local_time() -> None:
    h = _header()
    assert "Predmet:" in h and "Re: [Smart s.r.o.] Čaká sa na platbu" in h
    assert "2026-11-03 07:47" in h  # Europe/Bratislava
    assert "Od:" in h and "&quot;Kovacs Jozef&quot; &lt;jozef@example.test&gt;" in h
    assert "Komu:" in h and "eshop@smartsro.sk" in h
    assert "Kópia:" in h and "kopia@example.test" in h


def test_forward_header_escapes_values() -> None:
    h = forward_header_html(subject="<script>x</script>", date=None, from_name="a<b", from_email="a@b.test")
    assert "<script>" not in h and "&lt;script&gt;" in h
    assert "Dátum:" not in h


def test_forward_body_carries_note_header_and_quote_once() -> None:
    out = assemble_outgoing_html(
        user_html="<p>Posielam ďalej</p>",
        quote_html="<p>Bola zaplatená 2.11.2026</p>",
        signature_html=None,
        mode="forward",
        forward_header=_header(),
    )
    assert out.count("Pôvodná správa") == 1
    assert out.index("Pôvodná správa") < out.index("Kovacs Jozef") < out.index("Bola zaplatená")
    # the editor copy is never trusted: re-assembling from it does not duplicate the header
    again = assemble_outgoing_html(
        user_html=out,
        quote_html="<p>Bola zaplatená 2.11.2026</p>",
        signature_html=None,
        mode="forward",
        forward_header=_header(),
    )
    assert again.count("Kovacs Jozef") == 1 and strip_protected(again).count("Kovacs") == 0


def test_reply_has_no_forward_header() -> None:
    out = assemble_outgoing_html(
        user_html="<p>ok</p>", quote_html="<p>x</p>", signature_html=None, mode="reply", forward_header=_header()
    )
    assert "Pôvodná správa" not in out and "Kovacs" not in out
