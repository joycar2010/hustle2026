# 时间格式检查报告

**扫描时间：** 2026-02-24T16:20:57.538177
**发现问题总数：** 18

## 问题统计

| 严重程度 | 数量 |
|---------|------|
| 🔴 HIGH | 12 |
| 🟡 MEDIUM | 6 |
| 🟢 LOW | 0 |

---

## 详细问题列表


### 🔴 HIGH 优先级问题

#### api\v1\test.py:154

**问题代码：**
```
today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### api\v1\test.py:179

**问题代码：**
```
today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### services\account_service.py:47

**问题代码：**
```
today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### services\account_service.py:526

**问题代码：**
```
today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### services\account_service.py:556

**问题代码：**
```
today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### services\mt5_client.py:51

**问题代码：**
```
time_since_last_request = (datetime.now() - self.last_successful_request).total_seconds()
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### services\mt5_client.py:70

**问题代码：**
```
time_since_attempt = (datetime.now() - self.last_connection_attempt).total_seconds()
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### services\mt5_client.py:80

**问题代码：**
```
self.last_connection_attempt = datetime.now()
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### services\mt5_client.py:98

**问题代码：**
```
self.last_successful_request = datetime.now()
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### services\mt5_client.py:159

**问题代码：**
```
self.last_successful_request = datetime.now()
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### services\mt5_client.py:191

**问题代码：**
```
self.last_successful_request = datetime.now()
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---

#### services\mt5_client.py:220

**问题代码：**
```
time_since_last = (datetime.now() - self.last_successful_request).total_seconds()
```

**问题描述：** 使用本地时间 datetime.now()，应改为 datetime.utcnow()
**修复建议：** `datetime.utcnow()`

---


### 🟡 MEDIUM 优先级问题

#### api\v1\trading.py:385

**问题代码：**
```
query_datetime_start = datetime.strptime(date, "%Y-%m-%d")
```

**问题描述：** 使用 strptime 解析时间但未指定时区
**修复建议：** `添加 .replace(tzinfo=timezone.utc) 或使用 fromisoformat`

---

#### api\v1\trading_fix.py:293

**问题代码：**
```
query_datetime_start = datetime.strptime(date, "%Y-%m-%d")
```

**问题描述：** 使用 strptime 解析时间但未指定时区
**修复建议：** `添加 .replace(tzinfo=timezone.utc) 或使用 fromisoformat`

---

#### services\market_service.py:202

**问题代码：**
```
start_dt = start_dt.replace(tzinfo=None)
```

**问题描述：** 手动移除时区信息，可能导致时区混淆
**修复建议：** `保留时区信息或确保数据库支持时区`

---

#### services\market_service.py:207

**问题代码：**
```
end_dt = end_dt.replace(tzinfo=None)
```

**问题描述：** 手动移除时区信息，可能导致时区混淆
**修复建议：** `保留时区信息或确保数据库支持时区`

---

#### utils\time_utils.py:96

**问题代码：**
```
dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
```

**问题描述：** 手动移除时区信息，可能导致时区混淆
**修复建议：** `保留时区信息或确保数据库支持时区`

---

#### utils\time_utils.py:137

**问题代码：**
```
return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).replace(tzinfo=None)
```

**问题描述：** 手动移除时区信息，可能导致时区混淆
**修复建议：** `保留时区信息或确保数据库支持时区`

---

