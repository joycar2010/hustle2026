# 管理后台登录问题修复报告

## 问题描述

用户使用 admin/admin123 登录 https://admin.hustle2026.xyz/login 时提示"用户名或密码错误"。

## 错误信息

```
{"detail":"Login failed: password cannot be longer than 72 bytes, truncate manually if necessary (e.g. my_password[:72])"}
```

## 根本原因

### 1. bcrypt 版本不兼容
- 系统安装了 **bcrypt 5.0.0**
- passlib 1.7.4 与 bcrypt 5.x 不兼容
- passlib 在初始化时会检测 bcrypt 的 bug，使用超过 72 字节的测试密码
- bcrypt 5.x 严格限制密码长度不超过 72 字节，导致 passlib 初始化失败

### 2. 数据库中的密码哈希损坏
- 原密码哈希：`$2b$12$vh1JgVgE/zJr7KwnZxFDseSpJ24jZsTgvEICtWb9h/GofN8NiTuHm`
- bcrypt 验证时报错：`Invalid salt`
- 可能是之前使用不兼容版本生成的哈希

## 修复步骤

### 1. 降级 bcrypt 到兼容版本
```bash
cd /data/hustle2026/backend
/data/hustle2026/backend/venv/bin/pip install 'bcrypt<5.0.0'
```

**结果**：
- 卸载 bcrypt 5.0.0
- 安装 bcrypt 4.3.0
- passlib 可以正常工作

### 2. 重新生成密码哈希
使用 Python 脚本 `scripts/fix_admin_password.py` 直接更新数据库：

```python
from passlib.context import CryptContext
import asyncpg

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
password_hash = pwd_context.hash("admin123")

# 使用 asyncpg 更新数据库
await conn.execute(
    "UPDATE users SET password_hash = $1 WHERE username = $2",
    password_hash,
    "admin"
)
```

**新密码哈希**：`$2b$12$HfZYAQ66c9297bZ06JGGBOxxJxzjnYaZya0d4JqX6PTCJ8u48ii6W`

### 3. 重启后端服务
```bash
kill -9 <uvicorn_pid>
cd /data/hustle2026/backend
nohup /data/hustle2026/backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2 &
```

## 验证结果

### 修复前
```bash
curl -X POST https://admin.hustle2026.xyz/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}'

# 返回：
{"detail":"Login failed: password cannot be longer than 72 bytes..."}
```

### 修复后
```bash
curl -X POST https://admin.hustle2026.xyz/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}'

# 返回：
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user_id": "0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24",
  "username": "admin"
}
```

✅ 登录成功！

## 技术细节

### bcrypt 版本兼容性
- **bcrypt 4.x**：与 passlib 1.7.4 兼容
- **bcrypt 5.x**：API 变更，passlib 1.7.4 不兼容
  - 移除了 `__about__` 模块
  - 严格限制密码长度 ≤ 72 字节
  - passlib 初始化时会触发错误

### passlib 警告
```
(trapped) error reading bcrypt version
AttributeError: module 'bcrypt' has no attribute '__about__'
```
这是 passlib 尝试读取 bcrypt 版本时的警告，不影响功能。

### 为什么不能用 psql 直接更新
PostgreSQL 的 `$` 字符转义问题：
```sql
-- 错误：$ 被转义为 \
UPDATE users SET password_hash = '$2b$12$...' WHERE username = 'admin';
-- 结果：\b\2\...

-- 正确：使用参数化查询
UPDATE users SET password_hash = $1 WHERE username = $2;
```

## 预防措施

### 1. 锁定依赖版本
在 `requirements.txt` 中指定兼容版本：
```
bcrypt>=4.0.0,<5.0.0
passlib==1.7.4
```

### 2. 定期测试登录功能
添加健康检查端点测试认证功能。

### 3. 考虑升级 passlib
passlib 1.7.4 是 2020 年的版本，考虑升级到支持 bcrypt 5.x 的新版本（如果有）。

## 相关文件

- `backend/app/core/security.py` - 密码哈希和验证逻辑
- `backend/app/api/v1/auth.py` - 登录 API 端点
- `scripts/fix_admin_password.py` - 密码修复脚本
- `backend/requirements.txt` - Python 依赖（需更新）

## 修复日期
2026-03-31

## 修复人员
Claude Code (Sonnet 4.6)
