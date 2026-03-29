# MT5 Windows Agent

Windows服务器上的MT5实例管理服务，提供REST API接口用于部署、启动、停止和管理MT5实例。

## 功能

- 部署新的MT5实例
- 启动/停止/重启MT5实例
- 查询实例状态
- 列出所有实例
- 删除实例

## 部署步骤

### 1. 上传文件到Windows服务器

将以下文件上传到Windows服务器：
- `main.py`
- `requirements.txt`
- `deploy.bat`
- `install-service.bat`

### 2. 运行部署脚本

在Windows服务器上以管理员身份运行：
```cmd
deploy.bat
```

### 3. 安装为Windows服务（推荐）

以管理员身份运行：
```cmd
install-service.bat
```

这将使用NSSM将Agent安装为Windows服务，开机自动启动。

### 4. 手动启动（测试用）

如果不想安装为服务，可以手动启动：
```cmd
cd C:\MT5Agent
python main.py
```

## API端点

- `GET /` - 健康检查
- `GET /instances` - 列出所有实例
- `POST /instances/deploy` - 部署新实例
- `POST /instances/{port}/start` - 启动实例
- `POST /instances/{port}/stop` - 停止实例
- `POST /instances/{port}/restart` - 重启实例
- `GET /instances/{port}/status` - 获取实例状态
- `DELETE /instances/{port}` - 删除实例

## 配置

- 服务端口: 9000
- 配置文件: `C:\MT5Agent\instances.json`

## 验证

部署完成后，可以通过以下命令验证服务是否正常运行：

```cmd
curl http://localhost:9000/
```

应该返回：
```json
{"status": "healthy", "service": "MT5 Windows Agent"}
```
