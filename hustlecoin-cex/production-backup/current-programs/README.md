# 双服务器程序备份

C2 给对冲前加了独立 REST 双轴点差交叉确认防 WS 单源幻价插针，C3 用"预还闲币+活债驱动批量买还环"破解了 FORM -3087 平台抵押封顶导致的平仓死锁（10736 已还清关仓），C1 加了行情链路整体死亡时自动暂停借/开/平并显示红色「熔断中」横幅的全局熔断器（含快照刷新 5s→2s 提速）

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
