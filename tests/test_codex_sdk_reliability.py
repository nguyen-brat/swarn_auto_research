from __future__ import annotations

from types import SimpleNamespace

import pytest

from sdk.codex_app_server import client as client_module
from sdk.codex_app_server.client import AppServerClient
from sdk.codex_app_server.errors import ServerBusyError
from sdk.codex_app_server.retry import retry_on_overload


def test_retry_on_overload_defaults_are_long_enough(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0
    sleeps: list[float] = []

    monkeypatch.setattr(
        "sdk.codex_app_server.retry.random.uniform",
        lambda _low, _high: 0,
    )
    monkeypatch.setattr("sdk.codex_app_server.retry.time.sleep", sleeps.append)

    def fail_until_final_attempt() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 6:
            raise ServerBusyError(
                -32000,
                "server overloaded",
                {"codex_error_info": "server_overloaded"},
            )
        return "ok"

    assert retry_on_overload(fail_until_final_attempt) == "ok"
    assert attempts == 6
    assert sum(sleeps) >= 20
    assert all(sleep <= 30 for sleep in sleeps)


def test_next_notification_raises_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeStdout:
        def readline(self) -> str:
            raise AssertionError("readline should not be called when select times out")

    observed_timeouts: list[float | None] = []

    def fake_select(
        read_list: list[object],
        _write_list: list[object],
        _error_list: list[object],
        timeout: float | None,
    ):
        observed_timeouts.append(timeout)
        return [], [], []

    monkeypatch.setattr(
        client_module,
        "select",
        SimpleNamespace(select=fake_select),
        raising=False,
    )

    sdk_client = AppServerClient()
    sdk_client._proc = SimpleNamespace(stdout=FakeStdout())

    with pytest.raises(TimeoutError, match="Timed out waiting for app-server message"):
        sdk_client.next_notification(timeout_s=0.01)

    assert observed_timeouts == [0.01]
