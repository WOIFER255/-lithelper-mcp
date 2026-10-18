"""MCP server exposing Literature Helper's科研通 download workflow."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import tempfile
import asyncio
from contextlib import contextmanager
import urllib.request
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("literature-helper")
_PROFILE_LOCK = threading.Lock()


@contextmanager
def _profile_file_lock():
    """Prevent separate MCP processes from sharing one Playwright profile."""
    home = os.environ.get("LITHELPER_HOME")
    lock_path = (Path(home).expanduser() if home else Path.home() / ".literature-helper").resolve() / "mcp-profile.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"Literature Helper 浏览器 profile 正被其他进程占用：{lock_path}") from exc
    try:
        os.write(fd, str(os.getpid()).encode("ascii", errors="ignore"))
        yield
    finally:
        os.close(fd)
        lock_path.unlink(missing_ok=True)


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


def _json_error(code: str, message: str, *, hint: str = "", retryable: bool = False) -> str:
    result: dict[str, Any] = {"ok": False, "code": code, "message": message, "retryable": retryable}
    if hint:
        result["hint"] = hint
    return json.dumps(result, ensure_ascii=False)


def _cli_command(*parts: str, config_path: str | None = None) -> list[str]:
    executable = os.environ.get("LITHELPER_BIN", "lithelper")
    config_path = config_path or os.environ.get("LITHELPER_CONFIG")
    command = [executable]
    if config_path:
        command.extend(["--config", config_path])
    command.extend(["--json", "--non-interactive", *parts])
    return command


def _cli_environment() -> dict[str, str]:
    """Use UTF-8 for child CLI output even when Windows locale is GBK."""
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


def _run_cli(*parts: str, timeout: float | None = None, config_path: str | None = None) -> tuple[Any, str, int]:
    """Run one CLI action while preventing concurrent profile use."""
    if timeout is None:
        timeout = float(os.environ.get("LITHELPER_TIMEOUT_SECONDS", "900"))
    try:
        with _PROFILE_LOCK, _profile_file_lock():
            completed = subprocess.run(
                _cli_command(*parts, config_path=config_path),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdin=subprocess.DEVNULL,
                env=_cli_environment(),
                timeout=timeout,
                check=False,
            )
    except FileNotFoundError:
        return None, "找不到 lithelper，请检查 LITHELPER_BIN", 127
    except subprocess.TimeoutExpired:
        return None, f"lithelper 在 {timeout:g} 秒内未完成", 124
    except OSError as exc:
        return None, f"无法启动 lithelper：{exc}", 126
    try:
        payload = _decode_json(completed.stdout)
    except json.JSONDecodeError:
        return None, completed.stderr.strip() or completed.stdout.strip() or "lithelper 返回了无效 JSON", completed.returncode
    if completed.returncode != 0 or (isinstance(payload, dict) and payload.get("ok") is False):
        return payload, _error_reason(payload, completed.stderr, completed.returncode), completed.returncode
    return payload, "", completed.returncode


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
        return _json_error("INPUT_EMPTY", "doi_or_title 不能为空")

    executable = os.environ.get("LITHELPER_BIN", "lithelper")
    config_path = os.environ.get("LITHELPER_CONFIG")
    selected_dir = download_dir or os.environ.get("LITHELPER_DOWNLOAD_DIR")
    if selected_dir:
        target_dir = Path(selected_dir).expanduser().resolve()
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return _json_error("DOWNLOAD_DIR_ERROR", f"无法创建下载目录 {target_dir}：{exc}")
    else:
        target_dir = None
    timeout = float(os.environ.get("LITHELPER_TIMEOUT_SECONDS", "900"))
    # Keep the existing fetch-specific command because it accepts --download-dir.
    command = _cli_command("fetch", query)
    if target_dir:
        command.extend(["--download-dir", str(target_dir)])
    try:
        with _PROFILE_LOCK, _profile_file_lock():
            completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, env=_cli_environment(), timeout=timeout, check=False)
    except FileNotFoundError:
        return _json_error("LITHELPER_NOT_FOUND", f"找不到 {executable!r}，请检查 LITHELPER_BIN")
    except subprocess.TimeoutExpired:
        return _json_error("TIMEOUT", f"lithelper 在 {timeout:g} 秒内未完成下载", retryable=True)
    except OSError as exc:
        return _json_error("PROCESS_START_ERROR", f"无法启动 lithelper：{exc}")
    try:
        payload = _decode_json(completed.stdout)
    except json.JSONDecodeError:
        return _json_error("INVALID_JSON", "lithelper 返回的不是有效 JSON：" + (completed.stderr.strip() or completed.stdout.strip()), retryable=True)
    if completed.returncode != 0 or (isinstance(payload, dict) and payload.get("ok") is False):
        return _json_error("LITHELPER_ERROR", _error_reason(payload, completed.stderr, completed.returncode), retryable=True)

    if auto_accept:
        if os.environ.get("LITHELPER_ALLOW_AUTO_ACCEPT") != "1":
            return json.dumps({"ok": False, "code": "AUTO_ACCEPT_NOT_ENABLED", "message": "auto_accept 会转移科研通积分；请先设置 LITHELPER_ALLOW_AUTO_ACCEPT=1", "retryable": False}, ensure_ascii=False)
        task_id = payload.get("id") if isinstance(payload, dict) else None
        task_id = task_id or (payload.get("task_id") if isinstance(payload, dict) else None)
        if not task_id:
            return json.dumps({"ok": False, "code": "TASK_ID_MISSING", "message": "下载成功，但 JSON 中没有找到任务 ID，无法自动接受文件", "retryable": False}, ensure_ascii=False)
        accepted = _run_lithelper_action("confirm", str(task_id), timeout)
        if accepted[0] is not None:
            return json.dumps({"ok": False, "code": "AUTO_ACCEPT_FAILED", "message": "PDF 已下载，但自动接受文件失败：" + accepted[0], "retryable": True}, ensure_ascii=False)

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
        return _json_error("PDF_PATH_MISSING", "下载命令成功，但 JSON 中没有找到 PDF 本地路径", retryable=True)

    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return json.dumps({"ok": True, "pdf_path": str(path.resolve()), "task_id": payload.get("id") if isinstance(payload, dict) else None}, ensure_ascii=False)


def _run_lithelper_action(action: str, task_id: str, timeout: float) -> tuple[str | None, Any]:
    """Run a JSON lithelper action and return (error, payload)."""
    payload, error, _ = _run_cli(action, task_id, "--headless", timeout=timeout)
    return (error or None), payload


def _direct_accept_task(task_id: str) -> Any:
    """Accept a site file directly when CLI state is stale/failed.

    This uses Literature Helper's own adapter/selectors and persistent profile,
    so it can handle the site's layui confirmation layer without JS injection.
    """
    async def run() -> Any:
        from literature_helper.config import AppConfig
        from literature_helper.models import TaskStatus
        from literature_helper.workflow import LiteratureWorkflow
        from playwright.async_api import async_playwright

        config_path = os.environ.get("LITHELPER_CONFIG")
        config = AppConfig.load(Path(config_path) if config_path else None)
        workflow = LiteratureWorkflow(config, output=lambda _message: None)
        task = workflow.store.get(task_id)
        if not task.request_url:
            raise ValueError("任务没有 request_url，无法打开科研通详情页")
        async with async_playwright() as playwright:
            context = await workflow._launch_context(playwright, headless=False)
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto(task.request_url, wait_until="domcontentloaded", timeout=60_000)
                await workflow.adapter.accept_uploaded_file(page)
                updated = workflow.store.update(
                    task.id,
                    TaskStatus.CONFIRMED,
                    message="已通过站点详情页同步采纳文件",
                    request_url=page.url,
                    error=None,
                )
                return updated.to_dict()
            finally:
                await workflow._safe_close_context(context)

    with _PROFILE_LOCK, _profile_file_lock():
        return asyncio.run(run())


@mcp.tool()
def accept_paper(task_id: str, approved: bool = False) -> str:
    """Accept a downloaded file and transfer科研通积分; requires explicit opt-in."""
    if not approved:
        return json.dumps({"ok": False, "code": "APPROVAL_REQUIRED", "message": "接受文件会转移科研通积分；请传入 approved=true 明确确认", "retryable": False}, ensure_ascii=False)
    error, payload = _run_lithelper_action("confirm", task_id.strip(), float(os.environ.get("LITHELPER_TIMEOUT_SECONDS", "900")))
    if error:
        if os.environ.get("LITHELPER_DIRECT_BROWSER_FALLBACK", "1") == "1":
            try:
                direct = _direct_accept_task(task_id.strip())
                return json.dumps({"ok": True, "method": "direct_browser_fallback", "task": direct}, ensure_ascii=False)
            except Exception as direct_error:
                error = f"{error}；浏览器兜底也失败：{direct_error}"
        return json.dumps({"ok": False, "code": "ACCEPT_FAILED", "message": error, "retryable": True}, ensure_ascii=False)
    return json.dumps({"ok": True, "task": payload}, ensure_ascii=False)


@mcp.tool()
def list_tasks() -> str:
    """List local Literature Helper tasks without publishing or downloading anything."""
    timeout = float(os.environ.get("LITHELPER_READ_TIMEOUT_SECONDS", "60"))
    payload, error, _ = _run_cli("list", timeout=timeout)
    if error:
        return _json_error("LIST_FAILED", error, retryable=True)
    return json.dumps({"ok": True, "tasks": payload}, ensure_ascii=False)


@mcp.tool()
def get_task(task_id: str) -> str:
    """Read one task record, including request URL and current status."""
    timeout = float(os.environ.get("LITHELPER_READ_TIMEOUT_SECONDS", "60"))
    payload, error, _ = _run_cli("show", task_id.strip(), timeout=timeout)
    if error:
        return json.dumps({"ok": False, "code": "TASK_READ_FAILED", "message": error, "task_id": task_id, "retryable": True}, ensure_ascii=False)
    return json.dumps({"ok": True, "task": payload}, ensure_ascii=False)


@mcp.tool()
def download_existing(task_id: str, download_dir: str | None = None, high_speed: bool = False) -> str:
    """Resume an existing task without publishing a duplicate request."""
    target_dir = Path(download_dir).expanduser().resolve() if download_dir else None
    if target_dir:
        target_dir.mkdir(parents=True, exist_ok=True)
    parts = ["recover", task_id.strip()]
    if target_dir:
        parts.extend(["--download-dir", str(target_dir)])
    temporary_config: Path | None = None
    config_path = os.environ.get("LITHELPER_CONFIG")
    if high_speed and config_path:
        try:
            config_data = json.loads(Path(config_path).read_text(encoding="utf-8"))
            config_data["prefer_high_speed_download"] = True
            handle, temp_name = tempfile.mkstemp(prefix="lithelper-mcp-", suffix=".json")
            os.close(handle)
            temporary_config = Path(temp_name)
            temporary_config.write_text(json.dumps(config_data, ensure_ascii=False, indent=2), encoding="utf-8")
            config_path = str(temporary_config)
        except (OSError, json.JSONDecodeError) as exc:
            return json.dumps({"ok": False, "task_id": task_id, "error": f"无法准备高速通道配置：{exc}"}, ensure_ascii=False)
    try:
        payload, error, _ = _run_cli(*parts, config_path=config_path)
    finally:
        if temporary_config:
            temporary_config.unlink(missing_ok=True)
    if error:
        return json.dumps(
            {"ok": False, "task_id": task_id, "error": error,
             "hint": "若任务处于待确认状态，请先调用 accept_paper(task_id, approved=true)，再重试。"},
            ensure_ascii=False,
        )
    return json.dumps({"ok": True, "task": payload, "high_speed_requested": high_speed}, ensure_ascii=False)


if __name__ == "__main__":
    threading.Thread(target=_run_startup_update_check, daemon=True).start()
    mcp.run()
