# MT5环境诊断脚本

Write-Host "=== MT5环境诊断 ===" -ForegroundColor Green

# 1. 检查MT5安装路径
Write-Host "`n[1/5] 检查MT5安装路径..." -ForegroundColor Yellow
$mt5Paths = @(
    "C:\Program Files\MetaTrader 5\terminal64.exe",
    "C:\Program Files (x86)\MetaTrader 5\terminal64.exe",
    "D:\MetaTrader 5\terminal64.exe",
    "C:\MT5\terminal64.exe"
)

$foundPath = $null
foreach ($path in $mt5Paths) {
    if (Test-Path $path) {
        Write-Host "  找到MT5: $path" -ForegroundColor Green
        $foundPath = $path
        break
    }
}

if (-not $foundPath) {
    Write-Host "  未在标准路径找到MT5" -ForegroundColor Yellow
}

# 2. 检查MT5进程
Write-Host "`n[2/5] 检查MT5进程..." -ForegroundColor Yellow
$mt5Processes = Get-Process -Name terminal64,terminal -ErrorAction SilentlyContinue
if ($mt5Processes) {
    Write-Host "  找到 $($mt5Processes.Count) 个MT5进程:" -ForegroundColor Green
    $mt5Processes | Select-Object -First 3 | ForEach-Object {
        Write-Host "    PID=$($_.Id) Path=$($_.Path)"
        if (-not $foundPath -and $_.Path) {
            $foundPath = $_.Path
        }
    }
} else {
    Write-Host "  未找到MT5进程" -ForegroundColor Red
}

# 3. 检查Python环境
Write-Host "`n[3/5] 检查Python环境..." -ForegroundColor Yellow
$pythonPath = "D:\QHMT5\runtime\releases\v1\venv-ic\Scripts\python.exe"
if (Test-Path $pythonPath) {
    Write-Host "  Python: $pythonPath" -ForegroundColor Green
} else {
    Write-Host "  Python未找到" -ForegroundColor Red
}

# 4. 创建测试脚本
Write-Host "`n[4/5] 创建MT5测试脚本..." -ForegroundColor Yellow
$testCode = @'
import MetaTrader5 as mt5

print("=== MT5 Initialize Test ===")
print()

# Test 1: Default
print("[Test 1] mt5.initialize()")
if mt5.initialize():
    print("  SUCCESS")
    print(f"  Version: {mt5.version()}")
    mt5.shutdown()
else:
    error = mt5.last_error()
    print(f"  FAILED: {error}")

# Test 2: With path (if MT5 found)
mt5_path = "$($foundPath -replace '\\terminal64.exe', '')"
if mt5_path:
    print(f"\n[Test 2] mt5.initialize(path='{mt5_path}')")
    if mt5.initialize(path=mt5_path):
        print("  SUCCESS with path")
        info = mt5.terminal_info()
        if info:
            print(f"  Terminal: {info.name}")
            print(f"  Path: {info.path}")
        mt5.shutdown()
    else:
        error = mt5.last_error()
        print(f"  FAILED: {error}")
'@

$testCode | Out-File -Encoding UTF8 D:\test_mt5.py

# 5. 执行测试
Write-Host "`n[5/5] 执行MT5初始化测试..." -ForegroundColor Yellow
if (Test-Path $pythonPath) {
    & $pythonPath D:\test_mt5.py
} else {
    Write-Host "  无法执行测试" -ForegroundColor Red
}

# 总结
Write-Host "`n=== 诊断总结 ===" -ForegroundColor Green
if ($foundPath) {
    $mt5Dir = if ($foundPath -match '\\terminal64.exe$') {
        Split-Path $foundPath
    } else {
        Split-Path (Split-Path $foundPath)
    }
    Write-Host "MT5路径: $mt5Dir" -ForegroundColor Cyan
    Write-Host "修复建议: 在Bridge代码中使用 mt5.initialize(path='$mt5Dir')" -ForegroundColor Yellow
} else {
    Write-Host "未找到MT5安装" -ForegroundColor Red
}
