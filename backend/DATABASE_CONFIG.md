# 数据库配置说明

## 配置文件位置
所有系统模块的数据库配置统一集中在：
```
backend/.env
```

## 数据库配置参数

### PostgreSQL配置
```bash
DATABASE_URL=postgresql://postgres:Lk106504@127.0.0.1:5432/postgres
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=postgres
DB_USER=postgres
DB_PASSWORD=Lk106504
```

### Redis配置
```bash
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
```

## 配置说明

1. **统一配置管理**
   - 所有模块（前端、后端、后台任务等）的数据库配置都从 `backend/.env` 文件读取
   - 修改配置只需要更新这一个文件

2. **密码要求**
   - PostgreSQL密码：`Lk106504`（不含特殊字符，确保asyncpg兼容性）
   - 密码已在PostgreSQL数据库中设置
   - 认证方式：md5（在pg_hba.conf中配置）

3. **配置模板**
   - 参考文件：`backend/.env.example`
   - 新环境部署时，复制该文件并修改相应参数

4. **安全建议**
   - 生产环境请修改默认密码
   - 不要将 `.env` 文件提交到版本控制系统
   - 定期更新密码并同步更新配置文件

## 修改配置后的操作

1. 更新 `backend/.env` 文件中的配置参数
2. 如果修改了数据库密码，需要同步更新PostgreSQL：
   ```sql
   ALTER USER postgres WITH PASSWORD '新密码';
   ```
3. 重启后端服务使配置生效

## 当前状态
✅ PostgreSQL密码：Lk106504
✅ 配置文件：backend/.env
✅ 后端服务：正常运行
✅ 登录功能：正常工作
