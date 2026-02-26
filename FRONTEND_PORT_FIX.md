# 前端 API 端口配置修复

## 问题描述
用户使用 `admin/admin123` 登录时提示 "Invalid username or password"，原因是前端连接到错误的后端端口。

## 根本原因
- **前端配置**: 连接到端口 **8001** (`http://13.115.21.77:8001`)
- **后端实际运行**: 端口 **8000** (`http://13.115.21.77:8000`)
- **结果**: 前端无法连接到后端 API，导致登录失败

## 修复内容

### 修改文件
**文件**: `frontend/.env`

**修改前**:
```env
VITE_API_BASE_URL=http://13.115.21.77:8001
VITE_WS_URL=ws://13.115.21.77:8001
```

**修改后**:
```env
VITE_API_BASE_URL=http://13.115.21.77:8000
VITE_WS_URL=ws://13.115.21.77:8000
```

### 重新构建
```bash
cd /c/app/hustle2026/frontend
npm run build
```

**构建结果**: ✅ 成功 (9.07s)

## 验证步骤

### 1. 检查前端配置
```bash
cat /c/app/hustle2026/frontend/.env
# 应该显示:
# VITE_API_BASE_URL=http://13.115.21.77:8000
# VITE_WS_URL=ws://13.115.21.77:8000
```

### 2. 检查后端运行状态
```bash
curl http://localhost:8000/docs
# 应该返回 API 文档页面
```

### 3. 测试登录
1. 清除浏览器缓存 (Ctrl+Shift+Delete)
2. 刷新页面 (Ctrl+F5)
3. 访问 http://13.115.21.77:3000/login
4. 使用凭据登录:
   - 用户名: `admin`
   - 密码: `admin123`

## 当前配置

| 组件 | 端口 | URL |
|------|------|-----|
| 后端 API | 8000 | http://13.115.21.77:8000 |
| 前端 Web | 3000 | http://13.115.21.77:3000 |
| WebSocket | 8000 | ws://13.115.21.77:8000 |

## 登录凭据

- **URL**: http://13.115.21.77:3000/login
- **用户名**: `admin`
- **密码**: `admin123`

## 故障排查

如果仍然无法登录：

### 1. 清除浏览器缓存
```
Chrome/Edge: Ctrl+Shift+Delete
Firefox: Ctrl+Shift+Delete
```
选择"缓存的图片和文件"，时间范围选择"全部时间"

### 2. 检查浏览器控制台
按 F12 打开开发者工具，查看 Console 和 Network 标签：
- 检查是否有 API 请求错误
- 确认请求 URL 是否为 `http://13.115.21.77:8000/api/v1/auth/login`

### 3. 检查后端日志
```bash
tail -f /tmp/backend.log | grep -E "login|auth|401|403"
```

### 4. 测试后端 API
```bash
curl -X POST http://13.115.21.77:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'
```

应该返回包含 token 的 JSON 响应。

## 相关文档

- [服务重启报告](SERVICE_RESTART_REPORT.md)
- [MT5 价格错误修复](BYBIT_MT5_FIX_SUMMARY.md)

---

**修复时间**: 2026-02-26 17:20 UTC
**状态**: ✅ 已完成
**前端构建**: ✅ 成功
**配置更新**: ✅ 端口 8001 → 8000
