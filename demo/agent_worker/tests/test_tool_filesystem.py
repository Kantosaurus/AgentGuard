"""Filesystem-tool tests using tmp_path."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.tools.list_directory import ListDirectory
from app.tools.read_file import ReadFile
from app.tools.write_file import WriteFile


@pytest.mark.asyncio
async def test_read_file_returns_content_first_4kb(tmp_path: Path):
    p = tmp_path / "a.txt"
    p.write_text("X" * 5000)
    out = await ReadFile().run("rid", path=str(p))
    assert len(out) == 4096
    assert out[0] == "X"


@pytest.mark.asyncio
async def test_read_file_short_passes_through(tmp_path: Path):
    p = tmp_path / "a.txt"
    p.write_text("hello")
    out = await ReadFile().run("rid", path=str(p))
    assert out == "hello"


@pytest.mark.skipif(os.name == "nt", reason="/etc/passwd is POSIX-only")
@pytest.mark.asyncio
async def test_read_file_etc_passwd_works():
    # /etc/passwd exists in the test container; reading it must not raise.
    out = await ReadFile().run("rid", path="/etc/passwd")
    assert "root" in out


@pytest.mark.asyncio
async def test_read_file_missing_returns_error_string(tmp_path: Path):
    out = await ReadFile().run("rid", path=str(tmp_path / "nope"))
    assert out.startswith("error:")


@pytest.mark.asyncio
async def test_write_file_redirects_outside_tmp_to_basename_in_tmp(tmp_path: Path,
                                                                  monkeypatch):
    monkeypatch.setenv("WRITE_FILE_TMP", str(tmp_path))
    out = await WriteFile().run("rid", path="/etc/cron.d/foo", content="data")
    assert "ok" in out
    assert (tmp_path / "foo").read_text() == "data"


@pytest.mark.asyncio
async def test_write_file_keeps_tmp_path(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WRITE_FILE_TMP", str(tmp_path))
    out = await WriteFile().run("rid", path=f"{tmp_path}/sub/x", content="data")
    assert "ok" in out
    assert (tmp_path / "sub" / "x").read_text() == "data"


@pytest.mark.asyncio
async def test_list_directory_returns_first_100(tmp_path: Path):
    for i in range(150):
        (tmp_path / f"f{i:03d}").write_text("")
    out = await ListDirectory().run("rid", path=str(tmp_path))
    lines = out.splitlines()
    assert len(lines) == 100
    assert lines[0] == "f000"


@pytest.mark.asyncio
async def test_list_directory_missing_returns_error(tmp_path: Path):
    out = await ListDirectory().run("rid", path=str(tmp_path / "nope"))
    assert out.startswith("error:")
