# Polyauto 运维记忆

## 2026-09-12：前端空白页根因与固定流程

- `polyauto.hustle2026.xyz` 使用 Nginx 静态目录 `/var/www/polyauto.hustle2026.xyz`。
- 前端部署后必须确保目录可遍历、文件可读取：目录权限 `755`，文件权限 `644`。
- 如果 `assets/*.js` 或 `assets/*.css` 被 Nginx 返回为 `text/html`，说明资源不可读并触发了 `try_files ... /index.html` 回退，浏览器会显示空白页。
- 每次同步 `ui/dist` 后执行：

  ```bash
  sudo find /var/www/polyauto.hustle2026.xyz -type d -exec chmod 755 {} +
  sudo find /var/www/polyauto.hustle2026.xyz -type f -exec chmod 644 {} +
  sudo nginx -t && sudo systemctl reload nginx
  ```

- 部署后必须验证：主页引用的 JS/CSS URL 返回 `200`，且 JS 为 `application/javascript`、CSS 为 `text/css`，不能只验证主页 HTML 的 `200`。

## 当前运行边界

- BTC、ETH：polyauto 实盘 Worker；OpenClaw 负责调度、分析、风控和状态汇总。
- 天气、体育：Paper-only。
- OpenClaw 不持有私钥，不能绕过确定性风控直接下单。

## OpenClaw / LLM 调用核验

- `server/run_openclaw_paper.py` 只维护角色心跳和队列，不会自动调用模型。
- 模型调用必须通过 `/api/llm/advisor` 或 `/api/openclaw/consensus`，调用后 `/api/llm/usage` 才会出现模型 TOKEN 统计。
- 核验时同时查看 `LLM_PRIMARY_ENABLED`、`LLM_SECONDARY_ENABLED`、`LLM_ADVISOR_ENABLED` 和 `/api/llm/usage`；配置关闭或模型列表为空时，界面应显示“尚未调用 / 0 TOK”，不得伪造消耗数据。

## GitHub `poly` 备份认证工作区（2026-10-22）

以下记录用于后续备份操作；不保存 PAT、SSH 私钥、钱包私钥、API 密钥或恢复密钥。

- 已认证本机工作区：`D:\Dev\MixCodex\repo-poly`
- 远端仓库：`https://github.com/joycar2010/hustle2026.git`
- 目标分支：`poly`
- 认证方式：使用本机 Windows Git 凭据；服务器不保存 GitHub 登录凭据。临时 Deploy Key 不作为默认认证方式。
- 推送前先核对远端指针：`git ls-remote origin refs/heads/poly`
- 推送模式：`git push --force-with-lease=refs/heads/poly:<expected-sha> origin HEAD:refs/heads/poly`
- 禁止盲目使用 `--force`；推送后记录提交 SHA、时间和提交说明。
- 大型加密归档使用 Git LFS，并在 `.gitattributes` 中标记 `*.enc`；普通 Git 单文件不应超过 100 MB。
- 备份流程：服务器先生成本地快照、脱敏源码、加密归档和 SHA-256 清单，再由本机认证工作区推送。
- 安全边界：不上传 `.env`、历史环境文件、私钥、助记词、API 密钥、恢复密钥、`.venv`、`node_modules`、缓存、日志和 PID 文件；前端 `dist` 目录必须保留并校验。
