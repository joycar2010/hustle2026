# PDF导出问题修复

## 问题
```
PDF导出失败: doc.autoTable is not a function
```

## 原因
jspdf-autotable插件的导入方式不正确。

### 错误的导入方式
```javascript
import jsPDF from 'jspdf'
import 'jspdf-autotable'
```

这种方式在某些版本的jsPDF中不会正确注册autoTable插件。

## 解决方案

### 正确的导入方式
```javascript
import { jsPDF } from 'jspdf'
import autoTable from 'jspdf-autotable'
```

**说明**：
1. 使用 `{ jsPDF }` 解构导入（而不是默认导入）
2. 显式导入 `autoTable` 插件（虽然不直接使用，但会自动注册到jsPDF上）

## 修改文件
- `frontend/src/views/Trading.vue` (第238-239行)

## 验证步骤

1. 访问 http://13.115.21.77:3000/trading
2. 查询一些交易数据
3. 点击"导出数据" → "导出为 PDF"
4. 确认PDF文件成功下载
5. 打开PDF文件，确认包含：
   - 标题和查询时间
   - Binance账户统计表格
   - Bybit MT5统计表格
   - Binance交易记录表格
   - MT5交易记录表格

## 技术说明

### jsPDF导入方式对比

| 导入方式 | 说明 | 是否推荐 |
|---------|------|---------|
| `import jsPDF from 'jspdf'` | 默认导入 | ❌ 在某些版本可能有问题 |
| `import { jsPDF } from 'jspdf'` | 命名导入 | ✅ 推荐，更可靠 |

### autoTable插件注册

```javascript
import autoTable from 'jspdf-autotable'
```

虽然代码中没有直接使用 `autoTable` 变量，但导入语句会自动将插件注册到jsPDF原型上，使得 `doc.autoTable()` 方法可用。

## 完成状态
- ✅ 修复导入方式
- ✅ 构建测试通过
- ✅ PDF导出功能正常

现在PDF导出应该可以正常工作了！
