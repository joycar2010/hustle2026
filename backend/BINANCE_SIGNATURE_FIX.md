# Binance 合约 API -1022 签名错误修复方案

## 问题分析

-1022 错误表示签名无效，通常由以下原因导致：

1. **API Secret 不正确**
2. **参数未按 ASCII 码排序**
3. **时间戳格式错误**（秒级 vs 毫秒级）
4. **签名生成步骤错误**
5. **请求头缺少 X-MBX-APIKEY**
6. **recvWindow 参数缺失或过小**

## 正确的签名生成流程

### 步骤 1: 准备参数

```python
params = {
    "timestamp": int(time.time() * 1000),  # 必须是毫秒级！
    "recvWindow": 60000  # 建议 60000ms，避免时间误差
}
```

**常见错误：**
- ❌ `timestamp = int(time.time())` （秒级）
- ✅ `timestamp = int(time.time() * 1000)` （毫秒级）

### 步骤 2: 按 ASCII 码排序参数

```python
sorted_params = sorted(params.items())
```

**常见错误：**
- ❌ 直接使用 `params.items()` 不排序
- ✅ 使用 `sorted(params.items())` 排序

### 步骤 3: 拼接查询字符串

```python
query_string = "&".join([f"{key}={value}" for key, value in sorted_params])
# 结果: recvWindow=60000&timestamp=1771591153668
```

### 步骤 4: 生成 HMAC SHA256 签名

```python
signature = hmac.new(
    api_secret.encode("utf-8"),
    query_string.encode("utf-8"),
    hashlib.sha256
).hexdigest()  # 转小写十六进制
```

**常见错误：**
- ❌ 使用 `.digest()` 返回字节
- ✅ 使用 `.hexdigest()` 返回十六进制字符串

### 步骤 5: 添加签名到参数

```python
params["signature"] = signature
```

**重要：** 签名必须在生成后添加，不能包含在待签名字符串中！

### 步骤 6: 设置请求头

```python
headers = {
    "X-MBX-APIKEY": api_key  # API Key 必须在请求头中
}
```

**常见错误：**
- ❌ 将 API Key 放在参数中
- ✅ 将 API Key 放在请求头 X-MBX-APIKEY 中

## 时间同步

Binance 要求时间戳误差不超过 recvWindow（默认 5000ms）。如果本地时间不准确，需要同步：

```python
def sync_time(self):
    local_time = int(time.time() * 1000)
    response = requests.get("https://fapi.binance.com/fapi/v1/time")
    server_time = response.json()["serverTime"]
    self.time_offset = server_time - local_time
```

使用时：
```python
timestamp = int(time.time() * 1000) + self.time_offset
```

## 完整示例代码

```python
import hmac
import hashlib
import time
import requests

class BinanceFuturesClient:
    def __init__(self, api_key, api_secret):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://fapi.binance.com"
        self.time_offset = 0

    def sync_time(self):
        local_time = int(time.time() * 1000)
        response = requests.get(f"{self.base_url}/fapi/v1/time")
        server_time = response.json()["serverTime"]
        self.time_offset = server_time - local_time

    def _sign(self, params):
        query_string = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
        return hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

    def get_account(self):
        params = {
            "timestamp": int(time.time() * 1000) + self.time_offset,
            "recvWindow": 60000
        }
        params["signature"] = self._sign(params)

        headers = {"X-MBX-APIKEY": self.api_key}

        response = requests.get(
            f"{self.base_url}/fapi/v2/account",
            params=params,
            headers=headers
        )
        return response.json()

# 使用示例
client = BinanceFuturesClient(api_key, api_secret)
client.sync_time()  # 先同步时间
account = client.get_account()
```

## 常见错误点总结

| 错误类型 | 错误示例 | 正确示例 |
|---------|---------|---------|
| 时间戳单位 | `int(time.time())` | `int(time.time() * 1000)` |
| 参数排序 | `params.items()` | `sorted(params.items())` |
| 签名转换 | `.digest()` | `.hexdigest()` |
| API Key 位置 | `params["apiKey"]` | `headers["X-MBX-APIKEY"]` |
| 签名时机 | 先添加签名再计算 | 先计算签名再添加 |
| recvWindow | 不设置或太小 | 设置为 60000 |
| 时间同步 | 不同步 | 调用 sync_time() |

## 验证步骤

1. **运行测试脚本**
   ```bash
   cd c:/app/hustle2026/backend
   python fix_binance_signature.py
   ```

2. **检查输出**
   - ✅ 时间同步成功
   - ✅ 请求成功
   - ✅ 返回账户数据

3. **确认错误已解决**
   - 不再出现 -1022 错误
   - 能正常获取账户信息

## 应用到生产代码

更新 `app/services/binance_client.py`：

1. 添加 `time_offset` 属性
2. 添加 `sync_time()` 方法
3. 在 `_request()` 中添加 `recvWindow` 参数
4. 确保时间戳使用 `int(time.time() * 1000) + self.time_offset`

## 故障排查

如果仍然出现 -1022 错误：

1. **验证 API 凭证**
   - 检查 API Key 和 Secret 是否正确
   - 确认没有多余的空格或换行符

2. **检查 API 权限**
   - 确认 API Key 已启用"Enable Futures"权限
   - 检查 IP 白名单设置

3. **调试签名生成**
   - 打印待签名字符串
   - 打印生成的签名
   - 与 Binance 官方示例对比

4. **检查网络**
   - 确认能访问 https://fapi.binance.com
   - 检查是否被防火墙拦截

## 参考文档

- Binance Futures API 文档: https://binance-docs.github.io/apidocs/futures/cn/
- 签名认证说明: https://binance-docs.github.io/apidocs/futures/cn/#signed-trade-user_data
