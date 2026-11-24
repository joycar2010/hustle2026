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
