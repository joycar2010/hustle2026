# 飞书云文档小组件 - 策略监控面板

## 功能特性

- ✅ 实时显示策略运行状态
- ✅ 市场数据实时图表（Binance & Bybit）
- ✅ 收益趋势可视化
- ✅ WebSocket实时推送
- ✅ 自动重连机制
- ✅ 响应式设计

## 文件结构

```
feishu-widget/
├── index.html       # 主页面
├── app.js          # 核心逻辑
├── style.css       # 样式文件
├── manifest.json   # 飞书小组件配置
└── README.md       # 说明文档
```

## 使用方式

### 方式1: 独立访问

直接在浏览器中打开：
```
http://13.115.21.77:3000/feishu-widget/index.html
```

### 方式2: 飞书云文档小组件

1. **上传小组件**
   - 登录飞书开放平台：https://open.feishu.cn/
   - 进入"应用管理" → "云文档小组件"
   - 点击"创建小组件"
   - 上传 `feishu-widget` 文件夹中的所有文件

2. **配置小组件**
   - 设置小组件名称：策略监控面板
   - 配置API地址：http://13.115.21.77:8000
   - 配置WebSocket地址：ws://13.115.21.77:8000/ws

3. **在云文档中使用**
   - 打开飞书云文档
   - 输入 `/` 调出小组件菜单
   - 搜索"策略监控面板"
   - 插入到文档中

### 方式3: 嵌入到现有页面

在任何HTML页面中嵌入：

```html
<iframe
  src="http://13.115.21.77:3000/feishu-widget/index.html"
  width="100%"
  height="800px"
  frameborder="0">
</iframe>
```

## 数据源

小组件从以下API获取数据：

- **策略列表**: `GET /api/v1/strategies`
- **市场数据**: `GET /api/v1/market/current`
- **WebSocket**: `ws://13.115.21.77:8000/ws`
  - `market_data` - 实时市场数据
  - `account_balance` - 账户余额更新

## 配置项

可以在 `app.js` 中修改以下配置：

```javascript
const API_BASE_URL = 'http://13.115.21.77:8000';  // API地址
const WS_URL = 'ws://13.115.21.77:8000/ws';       // WebSocket地址
```

刷新间隔（第27行）：
```javascript
setInterval(fetchStrategies, 10000); // 每10秒刷新
```

## 技术栈

- **前端框架**: 原生JavaScript (ES6+)
- **图表库**: ECharts 5.4.3
- **飞书SDK**: @lark-base-open/js-sdk
- **实时通信**: WebSocket

## 浏览器兼容性

- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

## 开发调试

1. 启动本地服务器：
```bash
cd frontend
npm run dev
```

2. 访问：
```
http://localhost:3000/feishu-widget/index.html
```

3. 打开浏览器开发者工具查看日志

## 部署

### 部署到生产环境

1. 将 `feishu-widget` 文件夹复制到 `frontend/public/` 目录
2. 构建前端项目：
```bash
cd frontend
npm run build
```

3. 部署到服务器后，访问：
```
http://your-domain.com/feishu-widget/index.html
```

### 更新API地址

如果API地址变更，需要修改 `app.js` 中的配置：

```javascript
const API_BASE_URL = 'http://your-new-api-url';
const WS_URL = 'ws://your-new-ws-url';
```

## 故障排查

### WebSocket连接失败

1. 检查WebSocket服务是否运行
2. 检查防火墙设置
3. 查看浏览器控制台错误信息

### 数据不显示

1. 检查API地址是否正确
2. 检查网络连接
3. 查看浏览器控制台Network标签

### 图表不显示

1. 确认ECharts库已加载
2. 检查容器元素是否存在
3. 查看浏览器控制台错误信息

## 更新日志

### v1.0.0 (2026-03-06)
- ✅ 初始版本发布
- ✅ 实时策略监控
- ✅ 市场数据图表
- ✅ 收益趋势图表
- ✅ WebSocket实时推送

## 联系方式

如有问题或建议，请联系开发团队。
