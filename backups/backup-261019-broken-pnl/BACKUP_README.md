# polyauto 当前版本备份：261019收益破损版

备份时间：2026-10-19 UTC  
来源主机：`18.179.50.168`  
来源目录：`/home/ec2-user/polymarketbot-auto`

本目录保存部署前的源代码快照和 systemd/nginx 配置归档。源代码归档保留前端 `ui/dist`、后端、策略、测试和 OpenClaw 文件；排除了 `.env`、私钥、虚拟环境、运行日志、缓存和 SQLite 运行库文件，避免把凭证提交到仓库。数据库当前仍留在服务器原位置，未被修改。

## 文件校验

```text
b4d1e111d0bcc08fa2cf8cd55968929c121daf367d7f6d178605b780823c4ad0  polyauto-261019-source-clean.tar.gz
ddd593ae218368df4150f44c351a81a3c8787c6b09068e5bc471854add97b44a  polyauto-261019-services.tar.gz
```

目标历史提交：`31e693b56a1d00e8b787eb4c1e9fb6aa4856e256`（`260919OpenClawAuto四产品调试初版`）。

