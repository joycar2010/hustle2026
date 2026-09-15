# 双服务器程序备份

召回提前借币与自定义币种监控；修复双服务器完整程序备份及 GitHub coin 提交历史自动刷新

当前运行目录的源码、前后端程序、static/dist/public 和 Rust 运行二进制均在对应主机归档内。
每个文件和归档分片的 SHA-256 见 manifest.json 与 *-files.json。
凭证、数据库、行情数据、依赖缓存和旧备份不在本次程序备份范围。

恢复到独立目录：先按编号拼接分片，校验 SHA-256，再解压；不要覆盖正在运行的系统。
```sh
cat python.tar.gz.part* > python.tar.gz
cat rust.tar.gz.part* > rust.tar.gz
mkdir python-restore rust-restore
tar -xzf python.tar.gz -C python-restore
tar -xzf rust.tar.gz -C rust-restore
```
