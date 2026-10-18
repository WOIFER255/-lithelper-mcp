# DeepSeek Harness 更新提示词

将下面整段提示词发送给 DeepSeek Harness：

```text
请更新本机已经安装的 literature-helper MCP，不要重新创建第二份 MCP 配置。

仓库：
https://github.com/WOIFER255/-lithelper-mcp.git

用途限制：
这个 MCP 只允许用于科研文献相关任务。下面的“不要调用下载/采纳”只适用于更新过程中的
只读验证阶段，不是对更新完成后正常使用的永久限制。更新完成后，用户仍然可以正常调用
download_paper 和 download_existing 下载科研文献；accept_paper 仍需用户明确确认积分转移。

更新步骤：
1. 找到现有 MCP 的本地仓库目录和 DeepSeek Harness profile；先读取当前配置，保留：
   - LITHELPER_HOME
   - LITHELPER_CONFIG
   - LITHELPER_BIN
   - LITHELPER_DOWNLOAD_DIR
   - Python 虚拟环境路径
   - 当前 Cordis profile 配置
2. 备份当前 Cordis patch 配置和 MCP 环境变量。不要备份或上传密码、验证码、Cookie、
   browser-profile、tasks.sqlite3 或 PDF。
3. 停止旧的 literature-helper MCP 子进程，避免两个进程同时占用同一个浏览器 profile。
4. 在仓库目录执行：

   git pull --ff-only origin master

   如果本地有未提交修改，先停止并报告，不要覆盖这些修改。
5. 使用当前 MCP 的同一个 Python 虚拟环境执行：

   python -m pip install -r requirements.txt

   不要切换到系统 Python，也不要删除现有的 Literature Helper 数据目录。
6. 检查 `server.py` 可以导入，并确认 MCP 工具注册成功。
7. 更新 DSH Cordis 配置。新增 MCP 必须使用 `- insert:`，不要使用顶层 `- id:`：

   - insert:
       - id: mcp-literature-helper
         name: "@deepseek-ai/dsh-mcp-client"
         config:
           serverName: literature-helper
           transport: stdio
           command: "<同一个虚拟环境的 Python 绝对路径>"
           args: ["<仓库绝对路径>\\server.py"]
           cwd: "<仓库绝对路径>"
           env:
             LITHELPER_BIN: "<同一虚拟环境中的 lithelper.exe>"
             LITHELPER_HOME: "<原来的 LITHELPER_HOME>"
             LITHELPER_CONFIG: "<原来的 LITHELPER_CONFIG>"
             LITHELPER_DOWNLOAD_DIR: "<原来的下载目录>"
             LITHELPER_TIMEOUT_SECONDS: "900"
           toolCallTimeoutMs: 900000
           failOnStartupError: true

8. 默认不要设置 `LITHELPER_ALLOW_AUTO_ACCEPT=1`。在更新过程的只读验证阶段不得调用
   `download_paper`、`download_existing` 或 `accept_paper`，以免更新时重复发布、下载或转移
   积分。更新完成后不要禁用这些工具；它们应恢复正常可用。
9. 重启 DSH profile，等待 MCP 工具发现完成，确认以下工具出现：
   - mcp__literature-helper__download_paper
   - mcp__literature-helper__download_existing
   - mcp__literature-helper__list_tasks
   - mcp__literature-helper__get_task
   - mcp__literature-helper__accept_paper
   - mcp__literature-helper__check_for_updates
10. 更新期间只做只读验证：调用 list_tasks 或 get_task 读取现有任务状态；不要调用下载、
    采纳、recover 或任何会访问科研通并改变任务状态的工具。验证结束后，报告 MCP 已恢复
    正常文献下载能力。

如果更新后的 CLI 工具调用在 30 秒或 900 秒后超时，优先检查 MCP 子进程是否把 stdin
隔离为 DEVNULL，以及是否有另一个 lithelper 进程占用同一浏览器 profile；不要重复启动多个
MCP 实例来“试试看”。

最终报告：
- Git 当前 commit
- Python 和 literature-helper 版本
- MCP 是否成功启动
- 已发现的工具名称
- 使用的仓库路径和 profile 路径
- 只读验证结果

如果 git pull、依赖安装、MCP 启动或工具发现失败，保留旧配置和旧版本，不要删除旧目录，
并报告具体错误。
```
