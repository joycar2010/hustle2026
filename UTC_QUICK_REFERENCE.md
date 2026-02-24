# UTC时间处理快速参考指南

**适用对象：** 开发团队所有成员
**版本：** 1.0.0
**最后更新：** 2026-02-24

---

## 🚀 快速开始

### 后端开发（Python）

```python
# 1. 导入时间工具
from app.utils.time_utils import utc_now, format_utc_time, today_start_utc

# 2. 获取当前UTC时间
now = utc_now()  # ✅ 正确
# now = datetime.now()  # ❌ 错误

# 3. API返回时间
return {
    "timestamp": format_utc_time(order.create_time)  # "2026-02-24T10:30:00Z"
}

# 4. 日期范围查询
today_start = today_start_utc()
```

### 前端开发（JavaScript/Vue）

```javascript
// 1. 导入时间工具
import { formatUTCTime, timeAgo, nowUTC } from '@/utils/timeUtils'

// 2. 显示时间
<td>{{ formatUTCTime(order.create_time) }}</td>
// 输出: "2026-02-24 18:30:00 (UTC+8)"

// 3. 显示相对时间
<td>{{ timeAgo(order.create_time) }}</td>
// 输出: "2小时前"

// 4. 发送UTC时间到后端
const data = { timestamp: nowUTC() }
```

---

## 📋 常用函数速查表

### 后端（Python）

| 需求 | 函数 | 示例 |
|------|------|------|
| 获取当前UTC时间 | `utc_now()` | `datetime(2026, 2, 24, 10, 30)` |
| 格式化为ISO格式 | `format_utc_time(dt)` | `"2026-02-24T10:30:00Z"` |
| 解析ISO时间字符串 | `parse_utc_time(str)` | `datetime(2026, 2, 24, 10, 30)` |
| 转换为时间戳（毫秒） | `to_timestamp_ms(dt)` | `1740394200000` |
| 从时间戳转换 | `from_timestamp_ms(ts)` | `datetime(2026, 2, 24, 10, 30)` |
| 获取今日开始时刻 | `today_start_utc()` | `datetime(2026, 2, 24, 0, 0, 0)` |
| 格式化日志时间 | `format_log_time(dt)` | `"2026-02-24 10:30:00 UTC"` |
| 格式化文件名时间 | `format_filename_time(dt)` | `"20260224_103000_UTC"` |

### 前端（JavaScript）

| 需求 | 函数 | 示例 |
|------|------|------|
| 格式化UTC时间 | `formatUTCTime(time)` | `"2026-02-24 18:30:00 (UTC+8)"` |
| 显示相对时间 | `timeAgo(time)` | `"2小时前"` |
| 获取当前UTC时间 | `nowUTC()` | `"2026-02-24T10:30:00.000Z"` |
| 紧凑格式（图表） | `formatCompact(time, 'medium')` | `"02-24 10:30"` |
| 解析UTC时间 | `parseUTCTime(str)` | `Date对象` |
| 转换为时间戳 | `toTimestampMs(time)` | `1740394200000` |
| 获取今日时间范围 | `getTodayUTCRange()` | `{start: "...", end: "..."}` |

---

## ✅ 正确示例

### 场景1：创建订单记录

```python
# ✅ 正确
from app.utils.time_utils import utc_now

order = OrderRecord(
    order_id=generate_id(),
    create_time=utc_now(),  # UTC时间
    # ...
)
```

### 场景2：API返回订单列表

```python
# ✅ 正确
from app.utils.time_utils import format_utc_time

return {
    "orders": [
        {
            "order_id": order.order_id,
            "create_time": format_utc_time(order.create_time),  # ISO 8601格式
            # ...
        }
        for order in orders
    ]
}
```

### 场景3：查询今日订单

```python
# ✅ 正确
from app.utils.time_utils import today_start_utc
from datetime import timedelta

today_start = today_start_utc()
today_end = today_start + timedelta(days=1)

orders = await db.execute(
    select(OrderRecord).where(
        OrderRecord.create_time >= today_start,
        OrderRecord.create_time < today_end
    )
)
```

### 场景4：前端显示订单时间

```vue
<!-- ✅ 正确 -->
<template>
  <div>
    <p>创建时间: {{ formatUTCTime(order.create_time) }}</p>
    <p>{{ timeAgo(order.create_time) }}</p>
  </div>
</template>

<script setup>
import { formatUTCTime, timeAgo } from '@/utils/timeUtils'
</script>
```

### 场景5：生成备份文件名

```python
# ✅ 正确
from app.utils.time_utils import format_filename_time

filename = f"backup_{format_filename_time()}.sql"
# 输出: "backup_20260224_103000_UTC.sql"
```

---

## ❌ 错误示例（避免）

### 错误1：使用本地时间

```python
# ❌ 错误
from datetime import datetime

now = datetime.now()  # 本地时间，不同服务器时区不同
order.create_time = now
```

### 错误2：不明确的时间格式

```python
# ❌ 错误
timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
# 缺少时区信息，无法判断是UTC还是本地时间

# ✅ 正确
from app.utils.time_utils import format_utc_time
timestamp = format_utc_time(datetime.utcnow())  # "2026-02-24T10:30:00Z"
```

### 错误3：前端依赖浏览器时区

```javascript
// ❌ 错误
const date = new Date(timestamp)
const display = date.toLocaleString()  // 不同用户看到不同时间

// ✅ 正确
import { formatUTCTime } from '@/utils/timeUtils'
const display = formatUTCTime(timestamp)  // 统一显示，明确标注时区
```

### 错误4：手动移除时区信息

```python
# ❌ 错误
dt = datetime.fromisoformat(time_str)
dt = dt.replace(tzinfo=None)  # 可能导致时区混淆

# ✅ 正确
from app.utils.time_utils import parse_utc_time
dt = parse_utc_time(time_str)  # 自动处理时区
```

---

## 🔍 常见问题排查

### 问题1：时间显示不正确

**症状：** 前端显示的时间与预期不符

**排查步骤：**
1. 检查后端返回的时间格式是否为ISO 8601（含Z后缀）
2. 检查前端是否使用了 `formatUTCTime()` 函数
3. 检查浏览器时区设置

**解决方案：**
```javascript
// 确保使用工具函数
import { formatUTCTime } from '@/utils/timeUtils'
const display = formatUTCTime(apiTime)
```

---

### 问题2：数据库查询时间范围不准确

**症状：** 查询今日数据时结果不完整

**排查步骤：**
1. 检查是否使用了 `datetime.now()` 而非 `datetime.utcnow()`
2. 检查时间范围计算是否正确

**解决方案：**
```python
from app.utils.time_utils import today_start_utc
from datetime import timedelta

# 正确的今日时间范围
today_start = today_start_utc()
today_end = today_start + timedelta(days=1)
```

---

### 问题3：日志时间混乱

**症状：** 日志中的时间与实际不符

**排查步骤：**
1. 检查日志记录是否使用了 `datetime.now()`
2. 检查日志格式是否包含时区信息

**解决方案：**
```python
from app.utils.time_utils import format_log_time

logger.info(f"Order created at {format_log_time()}")
# 输出: "Order created at 2026-02-24 10:30:00 UTC"
```

---

### 问题4：第三方API时区不一致

**症状：** 与Binance/Bybit等API交互时时间不匹配

**排查步骤：**
1. 查阅API文档确认时区约定
2. 检查API客户端是否正确转换时区

**解决方案：**
```python
# Binance API使用UTC时间
from app.utils.time_utils import to_timestamp_ms, utc_now

timestamp = to_timestamp_ms(utc_now())  # 毫秒时间戳
```

---

## 📚 完整文档链接

- **详细整改方案：** [UTC_STANDARDIZATION_PLAN.md](UTC_STANDARDIZATION_PLAN.md)
- **实施总结报告：** [UTC_IMPLEMENTATION_SUMMARY.md](UTC_IMPLEMENTATION_SUMMARY.md)
- **时间格式检查报告：** [TIME_FORMAT_REPORT.md](TIME_FORMAT_REPORT.md)

---

## 🛠️ 工具和脚本

### 运行时间格式检查

```bash
# 检查整个项目
python scripts/time_format_checker.py --project-root . --output report.md

# 只检查后端代码
python scripts/time_format_checker.py --project-root backend --output backend_report.md
```

### 运行单元测试

```bash
# 测试时间工具模块
pytest backend/tests/test_time_utils.py -v

# 测试API时间格式
pytest backend/tests/test_api_time_format.py -v
```

---

## 💡 开发提示

1. **IDE配置：** 配置代码检查规则，禁止使用 `datetime.now()`
2. **Code Review：** 重点检查时间相关代码
3. **提交前检查：** 运行时间格式检查脚本
4. **文档更新：** API文档中明确说明时间字段为UTC

---

## 📞 技术支持

**遇到问题？**
- 查阅完整文档：[UTC_STANDARDIZATION_PLAN.md](UTC_STANDARDIZATION_PLAN.md)
- 联系系统架构组
- 提交Issue到项目仓库

---

**记住：始终使用UTC时间，明确标注时区！**

**版本历史：**
- v1.0.0 (2026-02-24) - 初始版本
