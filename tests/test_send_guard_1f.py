"""Phase 1f send guard: outside prod only test SMTP + @smartmail.test / allowlist recipients."""

from __future__ import annotations

from email.message import EmailMessage

import pytest

from app.core.config import Settings
from app.mail.send_guard import (
    SendGuardError,
    assert_send_allowed,
    recipient_allowed,
    smtp_host_allowed,
)


def _msg(*recipients: str) -> EmailMessage:
    m = EmailMessage()
    m["From"] = "pilot@smartmail.test"
    m["To"] = ", ".join(recipients)
    m.set_content("test")
    return m


def test_1f_smtp_host_allowed_mailpit_and_localhost() -> None:
    settings = Settings(app_env="dev", mail_send_allow_real_server=False)
    assert smtp_host_allowed(settings, "mailpit")
    assert smtp_host_allowed(settings, "localhost")
    assert smtp_host_allowed(settings, "127.0.0.1")
    assert not smtp_host_allowed(settings, "mail2.nameserver.sk")
    assert not smtp_host_allowed(settings, "smtp.gmail.com")


def test_1f_smtp_host_real_requires_flag_outside_prod() -> None:
    blocked = Settings(app_env="test", mail_send_allow_real_server=False)
    allowed = Settings(app_env="test", mail_send_allow_real_server=True)
    assert not smtp_host_allowed(blocked, "mail2.nameserver.sk")
    assert smtp_host_allowed(allowed, "mail2.nameserver.sk")


def test_1f_smtp_host_prod_unrestricted() -> None:
    # prod still needs a real APP_SECRET_KEY / encryption — build via model_construct for unit shape
    settings = Settings.model_construct(app_env="prod", mail_send_allow_real_server=False)
    assert smtp_host_allowed(settings, "mail2.nameserver.sk")


def test_1f_recipient_smartmail_test_ok() -> None:
    settings = Settings(app_env="dev", mail_send_test_allowlist="")
    assert recipient_allowed(settings, "pilot@smartmail.test")
    assert recipient_allowed(settings, "Anyone@SmartMail.Test")
    assert not recipient_allowed(settings, "zakaznik@firma.sk")
    assert not recipient_allowed(settings, "eshop@smartsro.sk")


def test_1f_recipient_allowlist() -> None:
    settings = Settings(app_env="dev", mail_send_test_allowlist="qa@example.test, other@smartsro.sk")
    assert recipient_allowed(settings, "qa@example.test")
    assert recipient_allowed(settings, "other@smartsro.sk")
    assert not recipient_allowed(settings, "info@smartsro.sk")


def test_1f_recipient_still_restricted_with_real_smtp_flag() -> None:
    settings = Settings(app_env="dev", mail_send_allow_real_server=True, mail_send_test_allowlist="qa@example.test")
    assert recipient_allowed(settings, "qa@example.test")
    assert recipient_allowed(settings, "pilot@smartmail.test")
    assert not recipient_allowed(settings, "zakaznik@firma.sk")


def test_1f_assert_send_blocks_live_smtp_host() -> None:
    settings = Settings(app_env="dev", mail_send_allow_real_server=False)
    with pytest.raises(SendGuardError) as exc:
        assert_send_allowed(settings, _msg("pilot@smartmail.test"), host="smtp.provider.sk")
    assert exc.value.code == "smtp_host_not_allowed"


def test_1f_assert_send_blocks_live_recipient() -> None:
    settings = Settings(app_env="dev", mail_send_allow_real_server=False, smtp_host="mailpit")
    with pytest.raises(SendGuardError) as exc:
        assert_send_allowed(settings, _msg("eshop@smartsro.sk"), host="mailpit")
    assert exc.value.code == "recipient_not_allowed"
    assert "eshop@smartsro.sk" in (exc.value.detail or "")


def test_1f_assert_send_ok_mailpit_to_test_domain() -> None:
    settings = Settings(app_env="dev", mail_send_allow_real_server=False)
    assert_send_allowed(settings, _msg("pilot@smartmail.test", "cc@smartmail.test"), host="mailpit")
