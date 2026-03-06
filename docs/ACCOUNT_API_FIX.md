# 账户 API 凭证显示修复

## 问题描述

在 http://localhost:3000/accounts 页面中，点击账户编辑时，API 参数（api_key、api_secret）显示为空。

## 根本原因

后端 `AccountResponse` schema 中没有包含 `api_key` 和 `api_secret` 字段，导致 API 响应中不返回这些敏感信息。

## 修复方案

### 1. 更新 AccountResponse Schema

**文件**: `c:\app\hustle2026\backend\app\schemas\account.py`

**修改内容**:
```python
class AccountResponse(BaseModel):
    """Schema for account response"""

    account_id: UUID
    user_id: UUID
    platform_id: int
    account_name: str
    api_key: Optional[str] = None  # 新增：API Key
    api_secret: Optional[str] = None  # 新增：API Secret
    passphrase: Optional[str] = None  # 新增：Passphrase (for OKX)
    mt5_id: Optional[str] = None  # 新增：MT5 account ID
    mt5_server: Optional[str] = None  # 新增：MT5 server
    mt5_primary_pwd: Optional[str] = None  # 新增：MT5 password
    is_mt5_account: bool
    is_default: bool
    is_active: bool
    create_time: datetime
    update_time: datetime
```

### 2. 验证修复

**测试步骤**:
1. 登录系统: http://13.115.21.77:3000/login
2. 进入账户页面: http://13.115.21.77:3000/accounts
3. 点击任意账户的"编辑"按钮
4. 确认 API Key 和 API Secret 字段已正确显示

**API 测试**:
```bash
# 获取访问令牌
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' | \
  python -c "import sys, json; print(json.load(sys.stdin)['access_token'])")

# 获取账户列表
curl -s -X GET "http://localhost:8000/api/v1/accounts" \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool
```

**预期结果**:
```json
{
  "account_id": "...",
  "user_id": "...",
  "platform_id": 1,
  "account_name": "19906779799",
  "api_key": "sFKNMhedTpiEvSqPBUDYiiSUXvSEgZGTiwytDj3CkoELhPNRUlrP2jxzgXiABK6A",
  "api_secret": "Tsk0C3WqGWmm0g55FnCigTrbd9VH7EHtVlSago5MRnToKWdVWAzxxDr0xjcbcusq",
  "passphrase": null,
  "mt5_id": null,
  "mt5_server": null,
  "mt5_primary_pwd": null,
  "is_mt5_account": false,
  "is_default": true,
  "is_active": true,
  "create_time": "2026-02-20T10:17:12.238064",
  "update_time": "2026-02-20T11:53:41.360441"
}
```

## 安全注意事项

### 1. 前端显示建议

在前端显示 API 凭证时，建议：
- **默认隐藏**: 使用 `type="password"` 或遮罩显示
- **点击显示**: 提供"显示/隐藏"按钮
- **复制功能**: 提供复制到剪贴板功能

示例代码:
```vue
<template>
  <div>
    <label>API Key</label>
    <div class="input-group">
      <input
        :type="showApiKey ? 'text' : 'password'"
        v-model="account.api_key"
        readonly
      />
      <button @click="showApiKey = !showApiKey">
        {{ showApiKey ? '隐藏' : '显示' }}
      </button>
      <button @click="copyToClipboard(account.api_key)">
        复制
      </button>
    </div>
  </div>
</template>
```

### 2. 传输安全

- ✅ 使用 HTTPS 传输（生产环境必须）
- ✅ 使用 JWT 认证保护 API
- ✅ 仅返回当前用户的账户信息

### 3. 存储安全

- ✅ 数据库中的敏感信息应加密存储（建议使用 AES-256）
- ✅ 定期轮换 API 密钥
- ✅ 记录 API 密钥访问日志

## 关于 Binance API 调用

### 当前实现

系统使用**数据库中存储的 API 凭证**进行 Binance API 调用，而不是后台配置文件中的参数。

**调用流程**:
1. 用户登录系统
2. 前端请求账户列表: `GET /api/v1/accounts`
3. 后端从数据库查询当前用户的账户
4. 返回账户信息（包含 api_key 和 api_secret）
5. 前端显示账户列表
6. 用户点击账户查看余额时，后端使用该账户的 API 凭证调用 Binance API

**代码位置**:
- 账户查询: `backend/app/api/v1/accounts.py`
- Binance API 调用: `backend/app/services/account_service.py`
- API 客户端: `backend/app/services/binance_client.py`

### 验证方法

检查 `account_service.py` 中的 `get_binance_balance()` 方法:
```python
async def get_binance_balance(self, api_key: str, api_secret: str) -> AccountBalance:
    """Fetch Binance Futures account balance"""
    client = BinanceFuturesClient(api_key, api_secret)  # 使用传入的凭证
    # ...
```

这确认了系统使用的是数据库中存储的 API 凭证，而不是配置文件中的参数。

## 修复状态

✅ **已修复**: AccountResponse schema 已更新，包含所有必要的 API 凭证字段
✅ **已验证**: API 端点正确返回 api_key 和 api_secret
✅ **已重启**: 后端服务已重启并应用更改

## 后续建议

1. **前端更新**: 更新前端账户编辑表单，正确显示和处理 API 凭证
2. **加密存储**: 考虑在数据库中加密存储 API Secret
3. **审计日志**: 记录 API 凭证的访问和修改操作
4. **权限控制**: 确保只有账户所有者可以查看和修改 API 凭证
