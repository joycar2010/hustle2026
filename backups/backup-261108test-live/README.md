# 261108test实盘完善版

本目录是从 PolyDex 服务器 18.179.50.168 当前运行的 polyauto.hustle2026.xyz 采集的程序源码快照。

内容包括：

- /home/ec2-user/polymarketbot-auto 的后端、策略、OpenClaw、脚本、测试、文档和前端源码；
- ui/dist* 全部前端构建产物，保留当前及历史 dist 目录；
- /var/www/polyauto.hustle2026.xyz 当前网页发布目录和静态资源；
- 当前 polyauto Nginx 配置与 polymarket-auto* systemd 服务定义；
- server-auto/environment.redacted 仅记录环境变量名称，不含值。

为保护密钥和运行数据，本次 Git 提交不包含 .env 内容、数据库/SQLite WAL、私钥或 API 密钥、虚拟环境、node_modules、缓存、日志和运行时状态。数据库文件仍保留在服务器原位置，未删除、未修改。

完整文件清单和采集信息见 backup-manifest.json，文件校验值见 CHECKSUMS.sha256。
