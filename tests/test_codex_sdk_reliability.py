from __future__ import annotations

import typing
from types import SimpleNamespace

import pytest

from sdk.codex_app_server import client as client_module
from sdk.codex_app_server import api as api_module
from sdk.codex_app_server.api import AsyncCodex, Codex
from sdk.codex_app_server.client import AppServerClient
from sdk.codex_app_server.errors import ServerBusyError
from sdk.codex_app_server.generated.v2_all import ServiceTier
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


def test_stream_notification_timeout_uses_bounded_poll_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_module.time, "monotonic", lambda: 100.0)

    assert api_module._next_notification_timeout(200.0) == 60.0
    assert api_module._next_notification_timeout(120.0) == 20.0

    with pytest.raises(TimeoutError, match="Timed out waiting for turn notification"):
        api_module._next_notification_timeout(99.0)


def test_service_tier_accepts_priority_response_value() -> None:
    assert ServiceTier("priority") is ServiceTier.priority


@pytest.mark.asyncio
async def test_async_thread_run_accepts_notification_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[float | str | None] = []

    class FakeStream:
        async def aclose(self) -> None:
            observed.append("closed")

    class FakeTurn:
        id = "turn-1"

        def stream(self, notification_timeout_s: float | None = 600.0) -> FakeStream:
            observed.append(notification_timeout_s)
            return FakeStream()

    async def fake_turn(self, *_args, **_kwargs) -> FakeTurn:
        return FakeTurn()

    async def fake_collect(_stream, *, turn_id: str):
        assert turn_id == "turn-1"
        return SimpleNamespace(final_response="ok", items=[], usage=None)

    monkeypatch.setattr(api_module.AsyncThread, "turn", fake_turn)
    monkeypatch.setattr(api_module, "_collect_async_run_result", fake_collect)

    thread = api_module.AsyncThread(SimpleNamespace(), "thread-1")
    result = await thread.run("hello", notification_timeout_s=7200.0)

    assert result.final_response == "ok"
    assert observed == [7200.0, "closed"]


def test_sdk_public_type_hints_resolve() -> None:
    assert typing.get_type_hints(Codex.thread_start)
    assert typing.get_type_hints(Codex.thread_list)
    assert typing.get_type_hints(AsyncCodex.thread_start)
    assert typing.get_type_hints(AsyncCodex.thread_list)
