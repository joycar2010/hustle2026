# 261119testbtc5m 新版服务器备份

- 备份备注：261119testbtc5m新版
- 来源服务器：PolyDextest 18.177.149.23
- 域名：https://polytest.hustle2026.xyz/
- 采集时间：2026-11-19（UTC）
- Git 目标：joycar2010/hustle2026 的 poly 分支

## 归档内容

- backend/dashboard-source.tar.gz：当前 Dashboard 后端 release polytest-polyauto-a-20261118T000000Z 的程序与源代码。
- backend/native-btc5m-source.tar.gz：当前 native BTC 5m Paper/兼容后端 release polytest-native-btc5m-20261118T181500Z 的程序与源代码。
- frontend/polytest-paper-label-20261119T130200Z-dist.tar.gz：Nginx 当前实际指向的完整前端 dist，包含全部静态资源、图片、视频和构建产物。该归档已完整保留，未删除或覆盖任何 dist 内容。
- frontend/ui-source-polytest-polyauto-a-20261118T000000Z.tar.gz：与当前 Dashboard release 关联的前端源代码包（含 src/、package.json、锁文件和构建配置）。
- config/nginx-polytest.conf：当前域名的 Nginx 配置快照。
- config/systemd/：当前相关 systemd unit/drop-in 快照。
- CAPTURE_MANIFEST.json 和 SHA256SUMS：文件清单、大小及 SHA-256 校验值。

## 安全边界

归档只包含程序、源代码、前端构建产物和部署配置。为避免把凭据或运行时数据提交到 GitHub，归档明确排除了 .env*、数据库及 WAL/SHM、日志、.venv、node_modules、Python 缓存和 .pyc。数据库与密钥仍保留在服务器原位置，不在本次 Git 备份中。

## 复核

归档下载后重新生成的 SHA256SUMS 用于提交内容复核。提交前检查了 backend 归档中不存在 .env、数据库、WAL/SHM 或虚拟环境条目。
