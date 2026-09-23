# 双服务器程序备份

第一轮是聚合行右键菜单给已完成平仓的 PENDING_REPAY 仓也放了必然失败的「强制平仓」按钮（已改为按状态只显示可执行动作+逐笔中文状态标签），第二轮是规则弹窗把「未设置」渲染成绿色「允还」而手动推送币种的真实语义是未显式开启即禁止（已改为 默认灰/允绿/禁红 三态 chip，未设置一点即显式允许）——顺带查明那两笔 FIL 卡待还币纯属规则从未落库，并非还币功能故障。

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
