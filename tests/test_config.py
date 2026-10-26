from app.core.config import Settings


def test_internal_domains_are_normalised() -> None:
    s = Settings(internal_domains=" SmartSro.sk, example.org ,")
    assert s.internal_domain_list == ["smartsro.sk", "example.org"]


def test_secrets_are_not_printed() -> None:
    s = Settings(app_secret_key="super-secret-value")
    assert "super-secret-value" not in repr(s)
