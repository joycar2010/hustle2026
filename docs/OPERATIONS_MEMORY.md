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

## 历史运行边界（2026-09-12）

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
- 默认追加推送：`git push origin HEAD:refs/heads/poly`，保留远端备份历史。只有用户明确要求且确需覆盖历史时，核对远端指针后才使用 `--force-with-lease=refs/heads/poly:<expected-sha>`。
- 禁止盲目使用 `--force`；推送后记录提交 SHA、时间和提交说明。
- 大型加密归档使用 Git LFS，并在 `.gitattributes` 中标记 `*.enc`；普通 Git 单文件不应超过 100 MB。
- 备份流程：服务器先生成本地快照、脱敏源码、加密归档和 SHA-256 清单，再由本机认证工作区推送。
- 安全边界：明文 Git 可查阅树不包含 `.env`、历史环境文件、私钥、助记词、API 密钥、原始数据库、依赖、缓存、日志和 PID 文件；完整应用原件只进入加密归档。恢复密钥必须独立于仓库保管，绝不上传；前端 `dist` 目录必须保留并校验。

## 2026-10-24：方案 C 与双域名备份

- 当前 polyauto 生产仅 BTC Paper，实盘关闭。实际执行目录为 `/home/ec2-user/polymarketbot-auto/releases/c-paper-profit-20261024`，并非根目录 `bot/main.py`。
- systemd drop-in `polymarket-auto-btc-paper.service.d/c-strategy.conf` 与 `scripts/run_paper_asset_c.sh` 共同指向该 release，生产数据库仍为 `trades-auto.db`。
- 新增 Paper 当日收益率 12% 止盈：$100 基数对应 $12，锁定新开仓至北京时间次日零点，继续持仓管理，重启不解除当日锁定。
- A/B/C 影子组在 `/home/ec2-user/paper-ab/20261022T020933Z`，分别使用自己的 `ab.db`，不与生产账本合并。
- polyauto UI 的 A/B/C 影子对照在 BTC 卡右侧，盈亏和胜负标注为北京时间当日，买入/退出笔数为累计。
- poly 网页 API 已恢复：应用 `/home/ec2-user/polymarketbot`，服务 `polymarket-dashboard.service`，8787；恢复网页没有启动其交易 worker。
- 双域名备份目录：`backups/backup-261024方案C重置版`。完整原文件及数据库保存在 Git LFS 加密归档；Git 可查阅树是脱敏副本。
- 本次恢复密钥本机路径：`C:\Users\Administrator\poly-backup-keys\261024\restore.key`，不得加入 Git。服务器副本为 `/home/ec2-user/backups/poly-261024-c-reset/private/restore.key`。
- 继续使用 `D:\Dev\MixCodex\repo-poly` 的 Windows Git 认证。优先追加提交、保留旧历史；无覆盖必要时使用普通 fast-forward 推送。

## 2026-10-27：生产 D 参数与四组影子备份

- 生产 BTC 仍在 `releases/c-paper-profit-20261024` 执行，路径名未变；实际参数已同步 D：0.84–0.90、90–150 秒入场、30% 止损 / 确认 2 次、150 秒止损窗口。生产为 Paper、实盘关闭、日亏损熔断关闭、日止盈 10%。
- 当前 A/B/C/D 在 `/home/ec2-user/paper-ab/20261026T110000Z`，各组独立 `ab.db`；四组日亏损 1%、日止盈 12%。旧 A/B/C 目录继续留存，不混入生产账本。
- 备份标签为 `261027影子D组策略优化版`，仓库目录 `backups/backup-261027影子D组策略优化版`。范围仅 polyauto 域名，包含整个应用、整个 paper-ab、真实网站目录、全部 dist 和 13 个 SQLite 一致性快照。
- 此版本实际网站资源与应用 `ui/dist` 不是同一集合，恢复当前页面用 `web-roots/polyauto.hustle2026.xyz`，两套均保留。
- 服务器备份目录 `/home/ec2-user/backups/polyauto-261027-shadow-d`。完整原件与敏感配置只在 AES/PBKDF2+HMAC 加密归档；通过 Git LFS 保存，公开副本已脱敏。
- 恢复密钥独立放在本机 `C:\Users\Administrator\poly-backup-keys\261027\restore.key` 及服务器备份的 `private/restore.key`；不得提交 Git。
- 继续使用 `D:\Dev\MixCodex\repo-poly` 的 Windows Git 凭据追加推送 `poly`，不在服务器新增 GitHub 凭据。
