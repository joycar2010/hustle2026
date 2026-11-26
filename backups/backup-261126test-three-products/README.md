# 261126test三产品测试版

服务器 18.177.149.23，域名 polytest.hustle2026.xyz，备份采集时间 2026-11-26T01:50:28.523999+00:00 UTC。

`server-files/` 镜像服务器程序文件的绝对路径。当前前端根目录为 `/var/www/polytest-releases/polytest-products-ui-health-1f09281b7197`。共收录 3106 个服务器文件、83 个前端发布目录和 22 个额外命名的 dist 目录。空目录、文件模式、服务名称及采集时状态见 MANIFEST.json。每个文件的 SHA-256 列在 SHA256SUMS.txt。

`frontend-source-active/` 保存此次生产构建所用的开发工作区源文件、依赖锁和构建配置。使用同一份源码重新构建后，index.html、JavaScript 和 CSS 与服务器逐文件 SHA-256 一致。

服务代码包含三产品 r5 Paper 进程、结算任务、Dashboard、SOL API、观察与兑换任务。数据库、行情/交易记录、日志、运行环境凭据、TLS 私钥、第三方依赖安装目录排除在此程序快照之外。
