"""Tests for the UTF-8 encoding contract module."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from intellisource.core import encoding
from intellisource.core.encoding import (
    ENCODING,
    enforce_utf8_runtime,
    is_utf8_environment,
    read_text,
    write_text,
)


class _FakeStream:
    def __init__(self, *, reconfigure_error: Exception | None = None) -> None:
        self.encoding = "cp936"
        self.calls: list[str] = []
        self._error = reconfigure_error

    def reconfigure(self, *, encoding: str) -> None:
        if self._error is not None:
            raise self._error
        self.calls.append(encoding)
        self.encoding = encoding


class _NoReconfigureStream:
    encoding = "cp936"


def test_encoding_constant_is_utf8() -> None:
    assert ENCODING == "utf-8"


def test_read_write_text_round_trip_with_non_ascii(tmp_path: Path) -> None:
    target = tmp_path / "sub" / "note.txt"
    target.parent.mkdir()
    payload = "北京天安门 — café — \U0001f680"

    write_text(target, payload)

    assert read_text(target) == payload
    # The bytes on disk are UTF-8 regardless of the host locale.
    assert target.read_bytes() == payload.encode("utf-8")


def test_read_text_accepts_str_path(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    target.write_text("数据", encoding="utf-8")

    assert read_text(str(target)) == "数据"


def test_read_text_decodes_utf8_bytes(tmp_path: Path) -> None:
    target = tmp_path / "raw.txt"
    target.write_bytes("简体中文".encode("utf-8"))

    assert read_text(target) == "简体中文"


def test_enforce_reconfigures_stdout_and_stderr_to_utf8(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out, err = _FakeStream(), _FakeStream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    enforce_utf8_runtime()

    assert out.calls == ["utf-8"]
    assert err.calls == ["utf-8"]


def test_enforce_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _FakeStream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", _FakeStream())

    enforce_utf8_runtime()
    enforce_utf8_runtime()

    assert out.calls == ["utf-8", "utf-8"]
    assert out.encoding == "utf-8"


def test_enforce_noops_when_stream_lacks_reconfigure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "stdout", _NoReconfigureStream())
    monkeypatch.setattr(sys, "stderr", _NoReconfigureStream())

    # Must not raise on streams replaced by a non-text object (e.g. a buffer).
    enforce_utf8_runtime()


@pytest.mark.parametrize("error", [ValueError("detached"), OSError("closed")])
def test_enforce_swallows_reconfigure_errors(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    monkeypatch.setattr(sys, "stdout", _FakeStream(reconfigure_error=error))
    monkeypatch.setattr(sys, "stderr", _FakeStream(reconfigure_error=error))

    enforce_utf8_runtime()  # detached/closed stream is a no-op, not a crash


@pytest.mark.parametrize(
    ("out_enc", "fs_enc", "expected"),
    [
        ("utf-8", "utf-8", True),
        ("UTF-8", "utf8", True),
        ("cp936", "utf-8", False),
        ("utf-8", "ascii", False),
        ("gbk", "gbk", False),
    ],
)
def test_is_utf8_environment(
    monkeypatch: pytest.MonkeyPatch, out_enc: str, fs_enc: str, expected: bool
) -> None:
    monkeypatch.setattr(sys, "stdout", _FakeStream())
    sys.stdout.encoding = out_enc  # type: ignore[attr-defined]
    monkeypatch.setattr(encoding.sys, "getfilesystemencoding", lambda: fs_enc)

    assert is_utf8_environment() is expected
