# literature-helper MCP Server

这个 MCP Server 暴露 `download_paper`、`accept_paper` 和 `check_for_updates`。
`download_paper(doi_or_title, download_dir?, auto_accept?)` 通过
`subprocess` 调用 Literature Helper 的非交互 JSON CLI：

```text
lithelper --json --non-interactive fetch "10.1234/abcd"
```

成功时工具返回 PDF 的本地绝对路径；失败时返回科研通/`lithelper` 报告的错误原因。

## 先决条件

1. Python 3.11+、Google Chrome（或按 Literature Helper 文档安装 Playwright Chromium）。
2. 安装依赖：

   ```bash
   python -m venv .venv
   # Windows: .venv\\Scripts\\activate
   # macOS/Linux: source .venv/bin/activate
   python -m pip install -r requirements.txt
   ```

3. 初始化并登录科研通：

   ```bash
   lithelper init
   lithelper doctor
   lithelper login
   ```

如果你平时使用 Microsoft Edge，可以继续使用 Edge 完成日常浏览；但不要假设
`lithelper` 会自动读取 Edge 个人 profile 的 Cookie。推荐执行 `lithelper login
--manual-browser`，在工具打开的浏览器窗口中完成一次科研通登录。登录会话会保存到
`%LOCALAPPDATA%\\literature-helper\\browser-profile`，之后 MCP 调用会复用这份会话并
自动运行。当前 PyPI 文档明确保证的是 Google Chrome/Playwright 浏览器；如果你的版本
没有明确支持 `browser_channel: "msedge"`，请使用默认 Chrome 或 Playwright Chromium，
不要直接修改配置后假定 Edge 一定可用。

   验证 CLI：

   ```bash
   lithelper --json --non-interactive fetch "10.1234/abcd"
   ```

   登录会话失效、验证码或人工确认会返回非零退出码，MCP 工具会把 JSON 中的
   `error.message` 返回给客户端。不要把账号密码写进配置文件。

## 运行

```bash
python server.py
```

可选环境变量：`LITHELPER_BIN` 指定可执行文件路径，`LITHELPER_CONFIG` 指定
`config.json` 的绝对路径（推荐，这样 MCP 与手动登录使用同一份 profile），
`LITHELPER_HOME` 指定 Literature Helper 数据目录，`LITHELPER_TIMEOUT_SECONDS`
指定超时（默认 900 秒），`LITHELPER_DOWNLOAD_DIR` 指定默认下载目录，
`LITHELPER_UPDATE_CHECK=0` 可关闭启动时 PyPI 更新检查。例如 Windows：

```text
LITHELPER_HOME=C:\\Users\\me\\AppData\\Local\\literature-helper
LITHELPER_CONFIG=C:\\Users\\me\\AppData\\Local\\literature-helper\\config.json
```

## 客户端配置

### Claude Desktop

在 `claude_desktop_config.json` 的 `mcpServers` 中加入（把路径改成绝对路径）：

```json
{
  "mcpServers": {
    "literature-helper": {
      "command": "C:\\path\\to\\project\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\project\\server.py"],
      "env": {
        "LITHELPER_BIN": "C:\\path\\to\\project\\.venv\\Scripts\\lithelper.exe"
      }
    }
  }
}
```

macOS/Linux 示例：

```json
{
  "mcpServers": {
    "literature-helper": {
      "command": "/absolute/path/project/.venv/bin/python",
      "args": ["/absolute/path/project/server.py"],
      "env": {"LITHELPER_BIN": "/absolute/path/project/.venv/bin/lithelper"}
    }
  }
}
```

### Codex / DSH

在 MCP 配置的 `servers`（或等价的 MCP server 列表）中使用同样的 `command`、
`args`、`env` 三个字段；例如：

```json
{
  "servers": {
    "literature-helper": {
      "command": "/absolute/path/project/.venv/bin/python",
      "args": ["/absolute/path/project/server.py"],
      "env": {"LITHELPER_BIN": "/absolute/path/project/.venv/bin/lithelper"}
    }
  }
}
```

具体配置文件位置和键名以客户端当前版本为准；MCP 传输方式是 stdio。

### 指定下载目录与积分确认

也可以在调用工具时传入绝对目录：

```text
download_paper("10.1234/abcd", "D:\\Papers")
```

`accept_paper(task_id)` 和 `download_paper(..., auto_accept=true)` 会在科研通确认文件并
转移积分，默认拒绝执行。只有明确设置以下环境变量后才允许：

```text
LITHELPER_ALLOW_AUTO_ACCEPT=1
```

建议生产环境保持关闭，先让 MCP 返回下载结果和任务 ID，再由用户单独调用
`accept_paper`。这是不可逆的积分转移操作。

建议先在同一环境完成登录，再启动 MCP：

```bash
lithelper login --manual-browser
```

确认浏览器窗口显示登录成功后回到终端按 Enter。然后用同一 `LITHELPER_CONFIG`
启动 MCP。Edge、Codex IAB 和 Literature Helper 自己的 Playwright profile 不共享
Cookie；在其中一个浏览器登录，不代表另外两个环境已登录。

## 可行性核实

PyPI 的 `literature-helper` 项目说明（0.7.x）明确记录了：`lithelper fetch` 接受
DOI 或准确标题；`--json --non-interactive` 为 Agent 提供结构化输出；成功数据含
任务/下载记录；失败以非零退出码和 `{"ok":false,"error":{"message":...}}` 返回。
流程通过科研通浏览器会话完成求助、等待应助、下载和 PDF 检查，不绕过验证码或权限。
因此该 MCP 封装可以调用真实下载流程，但仍需要用户先完成科研通登录并拥有相应访问权限。
