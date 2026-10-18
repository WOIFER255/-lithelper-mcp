# Literature Helper MCP 操作技能

## 目标

用 `download_paper` 通过科研通下载单篇 DOI/准确标题，并返回本地 PDF 绝对路径。

## 必须的首次设置

1. 安装 `requirements.txt`。
2. 准备 Python 3.11+ 和 Chrome/Playwright 浏览器。
3. 在 MCP 使用的同一数据目录执行：

   ```text
   lithelper login --manual-browser
   ```

4. 在打开的 Literature Helper 浏览器中由用户完成账号、密码和验证码；回到终端按
   Enter 后才算登录完成。
5. 将 `LITHELPER_HOME` 或更稳妥的 `LITHELPER_CONFIG` 配置到 MCP Server 的环境变量。

## 运行规则

- MCP Server 只调用 `lithelper --json --non-interactive fetch`，不解析 TUI 文本。
- 不要把密码、验证码或浏览器 profile 提交到仓库。
- Edge、Codex IAB 与 Literature Helper Playwright profile 是不同会话；不能假设
  在 Edge 或 IAB 登录会自动让 CLI 登录。
- 首次真实验证应使用用户明确提供的 DOI/标题；流程可能会在科研通创建求助任务并等待应助。
- `downloaded_pending_review` 且 `validation.ok=true` 表示 PDF 已下载并通过基础检查。

## 本次实测

使用 DOI `10.1039/d5qi02181b` 完成了真实流程：科研通识别出标题，任务进入
`downloaded_pending_review`，PDF 为 27 页、约 3.1 MB、未加密，验证通过。
