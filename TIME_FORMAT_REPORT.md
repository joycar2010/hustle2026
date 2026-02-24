# 时间格式检查报告

**扫描时间：** 2026-02-24T16:12:35.969949
**发现问题总数：** 86

## 问题统计

| 严重程度 | 数量 |
|---------|------|
| 🔴 HIGH | 29 |
| 🟡 MEDIUM | 5 |
| 🟢 LOW | 52 |

---

## 详细问题列表


### 🔴 HIGH 优先级问题

#### test_binance_api.py:169

**问题代码：**
```
today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### test_binance_api.py:201

**问题代码：**
```
today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### test_binance_api.py:238

**问题代码：**
```
today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### test_binance_api.py:326

**问题代码：**
```
print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### test_bybit_api.py:42

**问题代码：**
```
print(f"\n测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### test_bybit_api_en.py:42

**问题代码：**
```
print(f"\nTest Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### .gitbackups\untracked-20260218_235140\backend\app\services\account_service.py:188

**问题代码：**
```
today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### .gitbackups\untracked-20260218_235140\backend\app\services\account_service.py:218

**问题代码：**
```
today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### backend\test_binance_endpoints.py:45

**问题代码：**
```
today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### backend\app\api\v1\system.py:151

**问题代码：**
```
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### backend\app\api\v1\system.py:188

**问题代码：**
```
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### backend\app\api\v1\system.py:285

**问题代码：**
```
"start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### backend\app\api\v1\system.py:568

**问题代码：**
```
timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### backend\app\api\v1\test.py:154

**问题代码：**
```
today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### backend\app\api\v1\test.py:179

**问题代码：**
```
today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### backend\app\services\account_service.py:33

**问题代码：**
```
if (datetime.now() - timestamp).total_seconds() < self._cache_ttl:
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### backend\app\services\account_service.py:39

**问题代码：**
```
self._cache[cache_key] = (data, datetime.now())
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### backend\app\services\account_service.py:47

**问题代码：**
```
today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### backend\app\services\account_service.py:526

**问题代码：**
```
today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### backend\app\services\account_service.py:556

**问题代码：**
```
today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### backend\app\services\mt5_client.py:51

**问题代码：**
```
time_since_last_request = (datetime.now() - self.last_successful_request).total_seconds()
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### backend\app\services\mt5_client.py:70

**问题代码：**
```
time_since_attempt = (datetime.now() - self.last_connection_attempt).total_seconds()
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### backend\app\services\mt5_client.py:80

**问题代码：**
```
self.last_connection_attempt = datetime.now()
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### backend\app\services\mt5_client.py:98

**问题代码：**
```
self.last_successful_request = datetime.now()
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### backend\app\services\mt5_client.py:159

**问题代码：**
```
self.last_successful_request = datetime.now()
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### backend\app\services\mt5_client.py:191

**问题代码：**
```
self.last_successful_request = datetime.now()
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### backend\app\services\mt5_client.py:220

**问题代码：**
```
time_since_last = (datetime.now() - self.last_successful_request).total_seconds()
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### scripts\time_format_checker.py:30

**问题代码：**
```
'message': '使用本地时间 datetime.now()，应改为 datetime.utcnow()',
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### scripts\time_format_checker.py:36

**问题代码：**
```
'message': '使用本地日期 date.today()，应改为 datetime.utcnow().date()',
```

**问题描述：** 使用本地日期 date.today()，应改为 datetime.utcnow().date()
**修复建议：** `datetime.utcnow().date()`

---


### 🟡 MEDIUM 优先级问题

#### backend\app\api\v1\trading.py:385

**问题代码：**
```
query_datetime_start = datetime.strptime(date, "%Y-%m-%d")
```

**问题描述：** 使用 strptime 解析时间但未指定时区
**修复建议：** `添加 .replace(tzinfo=timezone.utc) 或使用 fromisoformat`

---

#### backend\app\api\v1\trading_fix.py:293

**问题代码：**
```
query_datetime_start = datetime.strptime(date, "%Y-%m-%d")
```

**问题描述：** 使用 strptime 解析时间但未指定时区
**修复建议：** `添加 .replace(tzinfo=timezone.utc) 或使用 fromisoformat`

---

#### backend\app\services\market_service.py:202

**问题代码：**
```
start_dt = start_dt.replace(tzinfo=None)
```

**问题描述：** 手动移除时区信息，可能导致时区混淆
**修复建议：** `保留时区信息或确保数据库支持时区`

---

#### backend\app\services\market_service.py:207

**问题代码：**
```
end_dt = end_dt.replace(tzinfo=None)
```

**问题描述：** 手动移除时区信息，可能导致时区混淆
**修复建议：** `保留时区信息或确保数据库支持时区`

---

#### scripts\time_format_checker.py:45

**问题代码：**
```
'suggestion': 'sa.TIMESTAMP(timezone=True)'
```

**问题描述：** 使用 TIMESTAMP WITHOUT TIME ZONE，建议改为 TIMESTAMP WITH TIME ZONE
**修复建议：** `sa.TIMESTAMP(timezone=True)`

---


### 🟢 LOW 优先级问题

#### scripts\time_format_checker.py:70

**问题代码：**
```
'message': '使用 new Date() 依赖浏览器时区',
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### .gitbackups\untracked-20260218_235140\frontend\src\views\Dashboard.vue:157

**问题代码：**
```
return num ? num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '0.00'
```

**问题描述：** 使用 toLocaleString 可能导致不同用户看到不同格式
**修复建议：** `统一使用 ISO 格式或明确标注时区`

---

#### frontend\src\components\dashboard\AssetDashboard.vue:290

**问题代码：**
```
return num ? num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '0.00'
```

**问题描述：** 使用 toLocaleString 可能导致不同用户看到不同格式
**修复建议：** `统一使用 ISO 格式或明确标注时区`

---

#### frontend\src\components\dashboard\SpreadChart.vue:245

**问题代码：**
```
const date = new Date(timestamp)
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\components\trading\AccountStatusPanel.vue:331

**问题代码：**
```
return num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
```

**问题描述：** 使用 toLocaleString 可能导致不同用户看到不同格式
**修复建议：** `统一使用 ISO 格式或明确标注时区`

---

#### frontend\src\components\trading\AccountStatusPanel.vue:357

**问题代码：**
```
const banUntilDate = new Date(banUntilMs)
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\components\trading\AccountStatusPanel.vue:358

**问题代码：**
```
const now = new Date()
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\components\trading\ManualTrading.vue:213

**问题代码：**
```
const date = new Date(timestamp)
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\components\trading\OrderMonitor.vue:151

**问题代码：**
```
const date = new Date(timestamp)
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\components\trading\SpreadChart.vue:276

**问题代码：**
```
const date = new Date(timestamp)
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\components\trading\SpreadDataTable.vue:71

**问题代码：**
```
timestamp: new Date(item.timestamp).getTime(),
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\components\trading\SpreadDataTable.vue:94

**问题代码：**
```
const date = new Date(timestamp)
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\views\Accounts.vue:364

**问题代码：**
```
const date = new Date(dateString)
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\views\Accounts.vue:365

**问题代码：**
```
return date.toLocaleString('zh-CN', {
```

**问题描述：** 使用 toLocaleString 可能导致不同用户看到不同格式
**修复建议：** `统一使用 ISO 格式或明确标注时区`

---

#### frontend\src\views\BinanceTest.vue:84

**问题代码：**
```
return val != null ? val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' USDT' : '0.00 USDT'
```

**问题描述：** 使用 toLocaleString 可能导致不同用户看到不同格式
**修复建议：** `统一使用 ISO 格式或明确标注时区`

---

#### frontend\src\views\BinanceTest.vue:117

**问题代码：**
```
return val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' USDT'
```

**问题描述：** 使用 toLocaleString 可能导致不同用户看到不同格式
**修复建议：** `统一使用 ISO 格式或明确标注时区`

---

#### frontend\src\views\BinanceTest.vue:126

**问题代码：**
```
const banUntilDate = new Date(banUntilMs)
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\views\BinanceTest.vue:127

**问题代码：**
```
const now = new Date()
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\views\BinanceTest.vue:182

**问题代码：**
```
return `${sign}${num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USDT`
```

**问题描述：** 使用 toLocaleString 可能导致不同用户看到不同格式
**修复建议：** `统一使用 ISO 格式或明确标注时区`

---

#### frontend\src\views\BybitTest.vue:200

**问题代码：**
```
return parseFloat(num).toLocaleString('en-US', {
```

**问题描述：** 使用 toLocaleString 可能导致不同用户看到不同格式
**修复建议：** `统一使用 ISO 格式或明确标注时区`

---

#### frontend\src\views\BybitTest.vue:213

**问题代码：**
```
const banUntilDate = new Date(banUntilMs)
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\views\BybitTest.vue:214

**问题代码：**
```
const now = new Date()
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\views\BybitTest.vue:252

**问题代码：**
```
const today = new Date()
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\views\PendingOrders.vue:122

**问题代码：**
```
const date = new Date(timestamp)
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\views\PendingOrders.vue:123

**问题代码：**
```
return date.toLocaleString('zh-CN', {
```

**问题描述：** 使用 toLocaleString 可能导致不同用户看到不同格式
**修复建议：** `统一使用 ISO 格式或明确标注时区`

---

#### frontend\src\views\Positions.vue:244

**问题代码：**
```
const today = new Date()
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\views\Positions.vue:257

**问题代码：**
```
const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()))
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\views\Positions.vue:260

**问题代码：**
```
const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1))
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\views\Positions.vue:275

**问题代码：**
```
const now = new Date()
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\views\Positions.vue:276

**问题代码：**
```
const twoHoursAgo = new Date(now.getTime() - 2 * 60 * 60 * 1000)
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\views\Positions.vue:298

**问题代码：**
```
const lastDay = new Date(firstDay)
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\views\Positions.vue:317

**问题代码：**
```
const lastDayOfMonth = new Date(parseInt(year), parseInt(month), 0).getDate()
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\views\Positions.vue:334

**问题代码：**
```
const start = new Date(startDate.value)
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\views\Positions.vue:335

**问题代码：**
```
const end = new Date(endDate.value)
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\views\Positions.vue:393

**问题代码：**
```
const jan4 = new Date(year, 0, 4)
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\views\Positions.vue:395

**问题代码：**
```
const firstMonday = new Date(jan4)
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\views\Positions.vue:397

**问题代码：**
```
const targetDate = new Date(firstMonday)
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\views\Positions.vue:499

**问题代码：**
```
const date = new Date(timestamp)
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\views\Positions.vue:500

**问题代码：**
```
return date.toLocaleString('zh-CN', {
```

**问题描述：** 使用 toLocaleString 可能导致不同用户看到不同格式
**修复建议：** `统一使用 ISO 格式或明确标注时区`

---

#### frontend\src\views\Positions.vue:511

**问题代码：**
```
const date = new Date(timestamp)
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\views\System.vue:1078

**问题代码：**
```
const date = new Date(dateString)
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\views\System.vue:1079

**问题代码：**
```
return date.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
```

**问题描述：** 使用 toLocaleString 可能导致不同用户看到不同格式
**修复建议：** `统一使用 ISO 格式或明确标注时区`

---

#### frontend\src\views\System.vue:1205

**问题代码：**
```
lastLogUpdate.value = new Date().toLocaleTimeString('zh-CN')
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\views\System.vue:1212

**问题代码：**
```
timestamp: new Date().toLocaleTimeString('zh-CN'),
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\views\System.vue:1217

**问题代码：**
```
timestamp: new Date().toLocaleTimeString('zh-CN'),
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\views\System.vue:1222

**问题代码：**
```
timestamp: new Date().toLocaleTimeString('zh-CN'),
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\views\System.vue:1227

**问题代码：**
```
timestamp: new Date().toLocaleTimeString('zh-CN'),
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\views\System.vue:1232

**问题代码：**
```
lastLogUpdate.value = new Date().toLocaleTimeString('zh-CN')
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\views\Trading.vue:363

**问题代码：**
```
const date = new Date(timestamp)
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\views\Trading.vue:364

**问题代码：**
```
return date.toLocaleString('zh-CN', {
```

**问题描述：** 使用 toLocaleString 可能导致不同用户看到不同格式
**修复建议：** `统一使用 ISO 格式或明确标注时区`

---

#### frontend\src\views\Trading_fix.vue:355

**问题代码：**
```
const date = new Date(timestamp)
```

**问题描述：** 使用 new Date() 依赖浏览器时区
**修复建议：** `使用 ISO 格式字符串或明确时区转换`

---

#### frontend\src\views\Trading_fix.vue:356

**问题代码：**
```
return date.toLocaleString('zh-CN', {
```

**问题描述：** 使用 toLocaleString 可能导致不同用户看到不同格式
**修复建议：** `统一使用 ISO 格式或明确标注时区`

---

