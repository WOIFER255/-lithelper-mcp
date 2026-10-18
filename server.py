"""MCP server exposing Literature Helper's科研通 download workflow."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("literature-helper")


def _first_value(value: Any, keys: set[str]) -> Any:
    """Find the first non-empty value for one of *keys* in nested JSON."""
    if isinstance(value, dict):
        for key in keys:
            candidate = value.get(key)
            if candidate not in (None, "", [], {}):
                return candidate
        for child in value.values():
            found = _first_value(child, keys)
            if found not in (None, "", [], {}):
                return found
    elif isinstance(value, list):
        for child in value:
            found = _first_value(child, keys)
            if found not in (None, "", [], {}):
                return found
    return None


def _decode_json(stdout: str) -> Any:
    """Decode CLI JSON, tolerating accidental surrounding whitespace/log lines."""
    text = stdout.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # JSON mode should be stdout-only, but accepting a final JSON object makes
        # the wrapper robust to older Literature Helper releases.
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def _error_reason(payload: Any, stderr: str, returncode: int) -> str:
    error = _first_value(payload, {"error"})
    if isinstance(error, dict):
        message = error.get("message") or error.get("reason")
        if message:
            return str(message)
    elif error:
        return str(error)
    if isinstance(payload, dict):
        for key in ("message", "reason", "detail"):
            if payload.get(key):
                return str(payload[key])
    return stderr.strip() or f"lithelper failed with exit code {returncode}"


@mcp.tool()
def download_paper(doi_or_title: str) -> str:
    """Download a paper through科研通 and return its absolute local PDF path."""
    query = doi_or_title.strip()
    if not query:
        return "错误：doi_or_title 不能为空"

    executable = os.environ.get("LITHELPER_BIN", "lithelper")
    config_path = os.environ.get("LITHELPER_CONFIG")
    timeout = float(os.environ.get("LITHELPER_TIMEOUT_SECONDS", "900"))
    command = [executable]
    if config_path:
        command.extend(["--config", config_path])
    command.extend(["--json", "--non-interactive", "fetch", query])
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return f"错误：找不到 {executable!r}。请先安装 literature-helper 并确保 lithelper 在 PATH 中。"
    except subprocess.TimeoutExpired:
        return f"错误：lithelper 在 {timeout:g} 秒内未完成下载"
    except OSError as exc:
        return f"错误：无法启动 lithelper：{exc}"

    try:
        payload = _decode_json(completed.stdout)
    except json.JSONDecodeError:
        return (
            "错误：lithelper 返回的不是有效 JSON："
            + (completed.stderr.strip() or completed.stdout.strip())
        )

    if completed.returncode != 0 or (isinstance(payload, dict) and payload.get("ok") is False):
        return "错误：" + _error_reason(payload, completed.stderr, completed.returncode)

    path_value = _first_value(
        payload,
        {
            "pdf_path",
            "pdfPath",
            "file_path",
            "filePath",
            "download_path",
            "downloadPath",
            "local_path",
            "localPath",
            "path",
        },
    )
    if isinstance(path_value, dict):
        path_value = _first_value(path_value, {"path", "absolute_path", "local_path"})
    if not isinstance(path_value, str) or not path_value.strip():
        return "错误：下载命令成功，但 JSON 中没有找到 PDF 本地路径"

    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return str(path.resolve())


if __name__ == "__main__":
    mcp.run()
