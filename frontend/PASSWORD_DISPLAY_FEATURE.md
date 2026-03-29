# 密码显示功能实现说明

## ✅ 已实现功能

### 1. 编辑用户 - 密码显示
**位置**：用户管理 → 用户账号 → 编辑用户

**实现**：
- 打开编辑模态框时，自动调用 `/api/v1/users/{user_id}/password` 加载密码
- 密码以星号形式显示：`••••••••`
- 点击眼睛图标可切换显示明文/隐藏
- 如果后端返回实际密码，则显示实际密码
- 如果后端不返回或加载失败，显示占位符星号

**保存逻辑**：
- 如果密码以 `••` 开头（占位符），则不发送到后端（保持原密码不变）
- 如果用户修改了密码，则发送新密码到后端
- 如果用户清空密码，则不发送（保持原密码不变）

### 2. 编辑账户 - API Secret 显示
**位置**：用户管理 → 绑定账户 → 编辑账户

**实现**：
- 打开编辑模态框时，自动调用 `/api/v1/accounts/{account_id}/secret` 加载 API Secret
- API Secret 以星号形式显示：`••••••••••••••••`
- 点击眼睛图标可切换显示明文/隐藏
- 同时加载 Passphrase（如果有）

**保存逻辑**：
- 如果 API Secret 以 `••` 开头（占位符），则不发送到后端
- 如果用户修改了 API Secret，则发送新值到后端
- Passphrase 同理

### 3. 编辑 MT5 客户端 - MT5 密码显示
**位置**：用户管理 → MT5账户管理 → 编辑MT5客户端

**实现**：
- 打开编辑模态框时，自动调用 `/api/v1/mt5-clients/{client_id}/password` 加载密码
- 密码以星号形式显示：`••••••••`
- 点击眼睛图标可切换显示明文/隐藏

**保存逻辑**：
- 如果密码以 `••` 开头（占位符），则不发送到后端
- 如果用户修改了密码，则发送新密码到后端

## 🔧 技术实现

### PasswordInput 组件
已有的 `PasswordInput.vue` 组件提供：
- 密码/明文切换功能（眼睛图标）
- 自动处理 `type="password"` 和 `type="text"` 切换
- 响应式设计

### API 端点需求
前端期望以下 API 端点返回密码数据：

1. **用户密码**：
   ```
   GET /api/v1/users/{user_id}/password
   Response: { "password": "actual_password_or_masked" }
   ```

2. **账户 API Secret**：
   ```
   GET /api/v1/accounts/{account_id}/secret
   Response: {
     "api_secret": "actual_secret_or_masked",
     "passphrase": "actual_passphrase_or_empty"
   }
   ```

3. **MT5 密码**：
   ```
   GET /api/v1/mt5-clients/{client_id}/password
   Response: { "mt5_password": "actual_password_or_masked" }
   ```

### 后端实现建议

**选项 1：返回实际密码（需要解密）**
```python
@router.get("/users/{user_id}/password")
async def get_user_password(user_id: UUID, current_user: User = Depends(get_current_admin)):
    user = await get_user_by_id(user_id)
    # 解密密码或返回明文
    return {"password": decrypt_password(user.password_hash)}
```

**选项 2：返回占位符（更安全）**
```python
@router.get("/users/{user_id}/password")
async def get_user_password(user_id: UUID, current_user: User = Depends(get_current_admin)):
    # 不返回实际密码，只返回占位符
    return {"password": "••••••••"}
```

前端会自动处理两种情况。

## 🎯 用户体验

### 编辑流程
1. 用户点击"编辑"按钮
2. 模态框打开，显示加载中...
3. 密码字段显示为星号：`••••••••`
4. 用户可以：
   - **不修改**：保持星号不变，保存时不发送密码（后端保持原密码）
   - **查看**：点击眼睛图标查看明文（如果后端返回了实际密码）
   - **修改**：清空并输入新密码，保存时发送新密码

### 安全考虑
- 密码在传输过程中使用 HTTPS 加密
- 占位符星号（`••`）不会被发送到后端
- 只有实际修改的密码才会被发送
- 后端可以选择不返回实际密码，只返回占位符

## 📝 测试清单

- [x] 编辑用户：密码显示为星号
- [x] 编辑用户：点击眼睛图标可查看/隐藏
- [x] 编辑用户：不修改密码时保存不发送密码字段
- [x] 编辑用户：修改密码后保存发送新密码
- [x] 编辑账户：API Secret 显示为星号
- [x] 编辑账户：点击眼睛图标可查看/隐藏
- [x] 编辑账户：不修改时保存不发送 API Secret
- [x] 编辑 MT5：密码显示为星号
- [x] 编辑 MT5：点击眼睛图标可查看/隐藏
- [x] 编辑 MT5：不修改时保存不发送密码

## 🚀 部署信息

- **版本**：`?v=1774754620`
- **主 JS**：`index-DbqdcQAs.js`
- **UserManagement JS**：`UserManagement-C3wPoDfD.js` (65.10 KB)
- **部署时间**：2026-03-28

## ⚠️ 注意事项

1. **后端 API 端点**：需要后端实现上述 3 个密码获取端点
2. **权限控制**：确保只有管理员可以访问这些端点
3. **密码解密**：如果后端存储的是加密密码，需要解密后返回
4. **占位符识别**：前端通过 `password.startsWith('••')` 识别占位符
5. **兼容性**：如果后端端点不存在，前端会自动降级显示占位符星号
