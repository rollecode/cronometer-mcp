"""Startup environment validation."""

import pytest

from cronometer_mcp.client import CronometerError, check_environment

_ALL = (
    "CRONOMETER_USERNAME",
    "CRONOMETER_PASSWORD",
    "CRONOMETER_ACCOUNT_TZ",
    "CRONOMETER_TOTP_SECRET",
)


@pytest.fixture
def clean_env(monkeypatch):
    for name in _ALL:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_missing_vars_are_all_reported_at_once(clean_env):
    with pytest.raises(CronometerError) as exc:
        check_environment()
    message = str(exc.value)
    for name in _ALL[:3]:
        assert name in message


def test_complete_env_passes(clean_env):
    clean_env.setenv("CRONOMETER_USERNAME", "me@example.com")
    clean_env.setenv("CRONOMETER_PASSWORD", "secret")
    clean_env.setenv("CRONOMETER_ACCOUNT_TZ", "Europe/Madrid")
    check_environment()


def test_invalid_timezone_is_rejected(clean_env):
    clean_env.setenv("CRONOMETER_USERNAME", "me@example.com")
    clean_env.setenv("CRONOMETER_PASSWORD", "secret")
    clean_env.setenv("CRONOMETER_ACCOUNT_TZ", "Mars/Olympus")
    with pytest.raises(CronometerError, match="not a known IANA timezone"):
        check_environment()
