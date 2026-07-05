"""
TCP listener robustness tests — the one internet-exposed, unauthenticated
attack surface (NinjaTrader connects here over a private/remote network).

Covers the abuse limits added to handle_client:
  - an endless stream with no newline is dropped (memory exhaustion)
  - an oversized single line is dropped
  - repeated bad tokens are throttled (brute-force / connect-flood)
  - a flood of malformed lines from an unauthenticated peer is cut off
  - the happy path still publishes a valid bar
"""

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.services.market_data import tcp_listener
from app.services.market_data.tcp_listener import (
    handle_client,
    _MAX_BUFFER_BYTES,
    _MAX_LINE_BYTES,
    _MAX_AUTH_FAILURES,
    _MAX_PREAUTH_MESSAGES,
)


class FakeReader:
    """Feeds queued byte chunks, then EOF (b"")."""
    def __init__(self, chunks):
        self._chunks = list(chunks)

    async def read(self, _n):
        if self._chunks:
            return self._chunks.pop(0)
        return b""


class FakeWriter:
    def __init__(self):
        self.closed = False

    def get_extra_info(self, _k):
        return ("127.0.0.1", 12345)

    def close(self):
        self.closed = True

    async def wait_closed(self):
        return None


def _valid_line(token="TM-AAAAAA"):
    # TOKEN|TIMESTAMP|SYMBOL|O|H|L|C|VOL|BAR_TYPE
    return f"{token}|2026-06-01T14:30:00Z|MES|5840.0|5841.0|5839.0|5840.5|100|1min"


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    """Stub the DB side-effects so no real pool is needed."""
    monkeypatch.setattr(tcp_listener, "_mark_connected", AsyncMock())
    monkeypatch.setattr(tcp_listener, "_mark_disconnected", AsyncMock())


@pytest.mark.asyncio
async def test_endless_stream_without_newline_is_dropped(monkeypatch):
    """A client that never sends a newline must not grow memory without bound."""
    resolve = AsyncMock(return_value="u-1")
    monkeypatch.setattr(tcp_listener, "_resolve_token", resolve)
    publish = AsyncMock()
    monkeypatch.setattr(tcp_listener, "publish_tick", publish)

    # One chunk larger than the buffer cap, no newline anywhere.
    flood = b"A" * (_MAX_BUFFER_BYTES + 1024)
    writer = FakeWriter()
    await handle_client(FakeReader([flood]), writer, db_pool=None, redis_client=None)

    assert writer.closed is True
    resolve.assert_not_awaited()   # never even got a full line
    publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_oversized_single_line_is_dropped(monkeypatch):
    resolve = AsyncMock(return_value="u-1")
    monkeypatch.setattr(tcp_listener, "_resolve_token", resolve)

    line = (b"X" * (_MAX_LINE_BYTES + 10)) + b"\n"
    writer = FakeWriter()
    await handle_client(FakeReader([line]), writer, db_pool=None, redis_client=None)

    assert writer.closed is True
    resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_repeated_bad_tokens_are_throttled(monkeypatch):
    """Every token fails to resolve — the connection must close after the cap."""
    resolve = AsyncMock(return_value=None)   # always a bad token
    monkeypatch.setattr(tcp_listener, "_resolve_token", resolve)

    # Send more bad-token lines than the failure cap allows.
    lines = "".join(_valid_line("TM-BAD" + str(i)) + "\n" for i in range(_MAX_AUTH_FAILURES + 20))
    writer = FakeWriter()
    await handle_client(FakeReader([lines.encode()]), writer, db_pool=None, redis_client=None)

    assert writer.closed is True
    # Stopped at exactly the failure cap — did not process the whole flood.
    assert resolve.await_count == _MAX_AUTH_FAILURES


@pytest.mark.asyncio
async def test_preauth_malformed_flood_is_cut_off(monkeypatch):
    """Malformed lines never reach token resolution, so a separate line cap applies."""
    resolve = AsyncMock(return_value=None)
    monkeypatch.setattr(tcp_listener, "_resolve_token", resolve)

    # Malformed (wrong field count) lines — parse fails, auth_failures never rises.
    lines = "".join("garbage-line\n" for _ in range(_MAX_PREAUTH_MESSAGES + 25))
    writer = FakeWriter()
    await handle_client(FakeReader([lines.encode()]), writer, db_pool=None, redis_client=None)

    assert writer.closed is True
    resolve.assert_not_awaited()   # nothing parsed → nothing resolved


@pytest.mark.asyncio
async def test_valid_bar_publishes(monkeypatch):
    resolve = AsyncMock(return_value="user-123")
    monkeypatch.setattr(tcp_listener, "_resolve_token", resolve)
    publish = AsyncMock()
    cache = AsyncMock()
    monkeypatch.setattr(tcp_listener, "publish_tick", publish)
    monkeypatch.setattr(tcp_listener, "cache_latest_tick", cache)

    writer = FakeWriter()
    await handle_client(
        FakeReader([(_valid_line() + "\n").encode()]),
        writer, db_pool=None, redis_client=None,
    )

    resolve.assert_awaited_once()
    publish.assert_awaited_once()
    # Published tick carries the parsed close for the resolved user.
    _args, _kwargs = publish.await_args
    assert _args[1] == "user-123"
    assert _args[2]["close"] == 5840.5
    assert writer.closed is True


@pytest.mark.asyncio
async def test_non_utf8_bytes_do_not_crash(monkeypatch):
    """Raw non-UTF8 bytes must be tolerated (decoded with errors='replace')."""
    resolve = AsyncMock(return_value=None)
    monkeypatch.setattr(tcp_listener, "_resolve_token", resolve)

    writer = FakeWriter()
    # Invalid UTF-8 sequence followed by a newline — must not raise.
    await handle_client(
        FakeReader([b"\xff\xfe\x00bad|line\n"]),
        writer, db_pool=None, redis_client=None,
    )
    assert writer.closed is True
