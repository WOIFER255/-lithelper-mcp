"""MCP server exposing Literature Helper's科研通 download workflow."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import urllib.request
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("literature-helper")


def _update_report() -> dict[str, Any]:
    """Return a best-effort PyPI update report without affecting MCP stdout."""
    package = "literature-helper"
    try:
        current = version(package)
    except PackageNotFoundError:
        return {"package": package, "installed": None, "latest": None, "error": "未安装 literature-helper"}
    try:
        request = urllib.request.Request(
            "https://pypi.org/pypi/literature-helper/json",
            headers={"User-Agent": "literature-helper-mcp/1.0"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            latest = json.load(response)["info"]["version"]
        return {
            "package": package,
            "installed": current,
            "latest": latest,
            "update_available": current != latest,
        }
    except Exception as exc:  # Update checks must never prevent MCP startup.
        return {"package": package, "installed": current, "latest": None, "error": str(exc)}


def _run_startup_update_check() -> None:
    if os.environ.get("LITHELPER_UPDATE_CHECK", "1").lower() in {"0", "false", "no"}:
        return
    report = _update_report()
    if report.get("update_available"):
        print(
            f"[literature-helper-mcp] literature-helper update available: "
            f"{report['installed']} -> {report['latest']}",
            file=sys.stderr,
        )


@mcp.tool()
def check_for_updates() -> str:
    """Check the installed literature-helper version against PyPI."""
    return json.dumps(_update_report(), ensure_ascii=False)


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
def download_paper(
    doi_or_title: str,
    download_dir: str | None = None,
    auto_accept: bool = False,
) -> str:
    """Download a paper and return its absolute local PDF path.

    ``auto_accept`` is disabled by default because confirming a file transfers
   科研通积分. It additionally requires ``LITHELPER_ALLOW_AUTO_ACCEPT=1``.
    """
    query = doi_or_title.strip()
    if not query:
        return "错误：doi_or_title 不能为空"

    executable = os.environ.get("LITHELPER_BIN", "lithelper")
    config_path = os.environ.get("LITHELPER_CONFIG")
    selected_dir = download_dir or os.environ.get("LITHELPER_DOWNLOAD_DIR")
    if selected_dir:
        target_dir = Path(selected_dir).expanduser().resolve()
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return f"错误：无法创建下载目录 {target_dir}：{exc}"
    else:
        target_dir = None
    timeout = float(os.environ.get("LITHELPER_TIMEOUT_SECONDS", "900"))
    command = [executable]
    if config_path:
        command.extend(["--config", config_path])
    command.extend(["--json", "--non-interactive", "fetch", query])
    if target_dir:
        command.extend(["--download-dir", str(target_dir)])
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

    if auto_accept:
        if os.environ.get("LITHELPER_ALLOW_AUTO_ACCEPT") != "1":
            return "错误：auto_accept 会转移科研通积分；请先设置 LITHELPER_ALLOW_AUTO_ACCEPT=1"
        task_id = payload.get("id") if isinstance(payload, dict) else None
        task_id = task_id or (payload.get("task_id") if isinstance(payload, dict) else None)
        if not task_id:
            return "错误：下载成功，但 JSON 中没有找到任务 ID，无法自动接受文件"
        accepted = _run_lithelper_action("confirm", str(task_id), timeout)
        if accepted[0] is not None:
            return "错误：PDF 已下载，但自动接受文件失败：" + accepted[0]

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


def _run_lithelper_action(action: str, task_id: str, timeout: float) -> tuple[str | None, Any]:
    """Run a JSON lithelper action and return (error, payload)."""
    executable = os.environ.get("LITHELPER_BIN", "lithelper")
    config_path = os.environ.get("LITHELPER_CONFIG")
    command = [executable]
    if config_path:
        command.extend(["--config", config_path])
    command.extend(["--json", "--non-interactive", action, task_id, "--headless"])
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        return str(exc), None
    try:
        payload = _decode_json(completed.stdout)
    except json.JSONDecodeError:
        return completed.stderr.strip() or completed.stdout.strip() or "无效 JSON", None
    if completed.returncode != 0 or (isinstance(payload, dict) and payload.get("ok") is False):
        return _error_reason(payload, completed.stderr, completed.returncode), payload
    return None, payload


@mcp.tool()
def accept_paper(task_id: str) -> str:
    """Accept a downloaded file and transfer科研通积分; requires explicit opt-in."""
    if os.environ.get("LITHELPER_ALLOW_AUTO_ACCEPT") != "1":
        return "错误：接受文件会转移科研通积分；请先设置 LITHELPER_ALLOW_AUTO_ACCEPT=1"
    error, payload = _run_lithelper_action("confirm", task_id.strip(), float(os.environ.get("LITHELPER_TIMEOUT_SECONDS", "900")))
    if error:
        return "错误：" + error
    return json.dumps(payload, ensure_ascii=False)


if __name__ == "__main__":
    threading.Thread(target=_run_startup_update_check, daemon=True).start()
    mcp.run()
