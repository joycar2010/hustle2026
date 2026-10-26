# 双服务器程序备份

20261027修复规则保存OK版

本归档记录当前生产双主机的前端、后端、源程序、生产静态资源和 Rust 运行二进制：

- Python 业务主机：`18.176.76.127`
- Rust 交易主机：`57.181.214.206`
- 域名：`coin.hustle2026.xyz`、`coinadmin.hustle2026.xyz`

`python-files.json`、`rust-files.json` 和 `manifest.json` 记录每个文件及归档分片的 SHA-256。归档不包含凭证、环境变量、数据库、运行时行情数据、依赖缓存、Rust `target` 构建缓存或历史备份目录；当前 `static/spa`、`static/admin-spa`、前端 `public` 资源和 Rust release 二进制均已包含。

恢复到独立目录时先校验分片哈希，再解压；不要覆盖正在运行的系统：

```sh
sha256sum python.tar.gz.part000 rust.tar.gz.part000
mkdir python-restore rust-restore
tar -xzf python.tar.gz.part000 -C python-restore
tar -xzf rust.tar.gz.part000 -C rust-restore
```
