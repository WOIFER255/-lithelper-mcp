# DeepSeek Harness 安装提示词

将下面整段提示词发送给 DeepSeek Harness：

```text
请安装并配置 GitHub 仓库 https://github.com/WOIFER255/-lithelper-mcp.git 中的 MCP Server。

用途限制：
1. 这个 MCP 只允许用于科研文献相关任务，例如根据 DOI 或准确标题查找、下载、整理和核对论文 PDF。
2. 处理与科研文献无关的任务时，不得调用这个 MCP，也不要把它当作通用网页下载器、文件管理器或浏览器控制器。
3. 不要把账号密码、验证码、浏览器 Cookie、浏览器 profile、任务数据库或本地 PDF 上传、复制或发送给任何外部服务。

安装步骤：
1. 将仓库克隆到一个稳定的本地目录，例如：
   C:\Users\<用户名>\Documents\literature-helper-mcp
2. 使用 Python 3.11+ 安装 requirements.txt。
3. 使用同一 Python 环境运行 server.py。
4. 通过 DeepSeek Harness 的官方 MCP Client 使用 stdio 传输配置：
   - serverName: literature-helper
   - transport: stdio
   - command: 该 Python 环境的绝对路径
   - args: server.py 的绝对路径
   - cwd: 仓库目录
5. 配置环境变量：
   - LITHELPER_BIN：lithelper 可执行文件的绝对路径
   - LITHELPER_HOME：Literature Helper 数据目录
   - LITHELPER_CONFIG：与登录会话对应的 config.json 绝对路径
   - 可选 LITHELPER_DOWNLOAD_DIR：默认 PDF 下载目录
6. 首次使用时运行 `lithelper login --manual-browser`，让用户自己在打开的浏览器中完成科研通登录、密码输入和验证码；不要代填或保存这些敏感信息。
7. 在 DSH 的 Cordis patch 中用 `- insert:` 新增插件（顶层 `- id:` 只覆盖已有插件），
   并将 `toolCallTimeoutMs` 设为 `900000`。
8. 重启 MCP Client，确认发现以下工具：
   - mcp__literature-helper__download_paper
   - mcp__literature-helper__download_existing
   - mcp__literature-helper__list_tasks
   - mcp__literature-helper__get_task
   - mcp__literature-helper__accept_paper
   - mcp__literature-helper__check_for_updates

调用规则：
1. 只有当用户明确提出文献查找、论文下载、DOI/标题检索或文献整理任务时，才允许调用 download_paper、download_existing、list_tasks 或 get_task。
2. download_paper 的第一个参数必须是用户提供的 DOI 或准确标题；第二个参数可以是用户指定的绝对下载目录。
3. 对已有任务优先使用 download_existing，不要重复发布同一 DOI；如果任务需要先采纳，先报告任务状态。
4. 下载完成后返回 PDF 的绝对路径，并说明任务状态。
5. `accept_paper(task_id, approved=true)` 会对当前任务执行一次采纳并转移科研通积分，只有用户在当前请求中明确确认该任务和积分转移时才允许调用。无人值守的 `download_paper(..., auto_accept=true)` 还必须设置 `LITHELPER_ALLOW_AUTO_ACCEPT=1`。
6. check_for_updates 只用于检查 literature-helper 版本，不要因为发现更新就自动升级或改变配置；先报告结果并等待用户决定。
7. 如果登录失效、验证码、权限不足、科研通无应助文件或任务失败，返回原始错误原因，不要绕过验证、验证码、访问限制或付费墙。

安装完成后，先只报告 MCP 是否成功启动和工具是否被发现；不要在没有文献任务时调用下载工具。
```
