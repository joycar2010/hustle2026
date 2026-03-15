# Bybit MT5 连接问题解决方案

## 当前问题
Python MetaTrader5 库无法连接到MT5终端，错误：`IPC initialize failed`

## 根本原因
MT5终端的Expert Advisors（EA交易）设置未启用API访问权限

## 解决步骤

### 1. 在MT5终端中启用API访问（必须操作）

1. 打开MetaTrader 5终端
2. 点击菜单：**工具 (Tools) → 选项 (Options)**
3. 选择 **EA交易 (Expert Advisors)** 标签页
4. **勾选以下所有选项**：
   - ✅ **允许算法交易 (Allow algorithmic trading)**
   - ✅ **允许DLL导入 (Allow DLL imports)**  ← 最关键
   - ✅ **允许从以下位置导入DLL (Allow imports of external experts)**
   - ✅ **允许WebRequest访问以下URL (Allow WebRequest for listed URL)** (可选)

5. 点击 **确定 (OK)** 保存设置
6. **完全关闭MT5终端**（右键任务栏图标 → 退出）
7. **重新启动MT5终端**
8. **重新登录您的账户**（账户: 3971962, 服务器: Bybit-Live-2）

### 2. 验证MT5设置

重启MT5后，在终端右下角应该看到：
- **AutoTrading** 按钮显示为绿色（表示算法交易已启用）
- 如果是红色，点击它切换为绿色

### 3. 测试连接

完成上述设置后，运行测试脚本：
```bash
cd c:/app/hustle2026/backend
python test_bybit_mt5.py
```

### 4. 如果仍然失败

#### 方案A：使用便携模式
在MT5安装目录创建空文件 `portable.txt`：
```bash
echo. > "C:/Program Files/MetaTrader 5/portable.txt"
```

#### 方案B：以管理员身份运行
1. 右键MT5终端图标
2. 选择"以管理员身份运行"
3. 重新登录账户

#### 方案C：检查防火墙
确保Windows防火墙允许MT5终端的入站/出站连接

## 技术说明

### MT5 API连接流程
```
Python Script → MetaTrader5.dll → Named Pipe (IPC) → MT5 Terminal
```

IPC timeout/failed 错误表示：
- MT5终端未启用DLL导入权限
- MT5终端的命名管道服务未启动
- 权限问题（需要管理员权限）

### 正确的连接代码
```python
import MetaTrader5 as mt5

# 方法1：连接到已登录的MT5终端（推荐）
if mt5.initialize():
    account_info = mt5.account_info()
    print(f"Connected to account: {account_info.login}")
    mt5.shutdown()

# 方法2：指定路径连接
if mt5.initialize(path="C:/Program Files/MetaTrader 5/terminal64.exe"):
    # ...
    mt5.shutdown()
```

## 常见错误码

- `-10003`: IPC initialize failed - EA设置未启用或MT5未运行
- `-10005`: IPC timeout - MT5终端无响应或权限问题
- `-10004`: IPC send failed - 通信失败
- `-1`: 未知错误 - 通常是MT5未初始化

## 下一步

完成MT5设置后，请告知我测试结果，我将：
1. 验证MT5连接正常
2. 更新后端代码以正确使用MT5 API
3. 重启后端服务
4. 验证整个系统运行正常
