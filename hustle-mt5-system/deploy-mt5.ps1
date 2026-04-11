<#
.SYNOPSIS
    Hustle2026 MT5 Bridge — Windows Server 2025 全自动部署脚本

.DESCRIPTION
    1. 修复 OpenSSH 密码登录（解决当前 SSH banner 问题）
    2. 在 D:\hustle-mt5\ 下部署系统账户桥接服务（端口 8001）
    3. 在 D:\hustle-mt5-cq987\ 下部署用户cq987桥接服务（端口 8002）
    4. 注册两个 Windows 服务（开机自启）
    5. 开放防火墙端口 8001 / 8002

.NOTES
    以管理员身份在 PowerShell 中运行：
    Set-ExecutionPolicy Bypass -Scope Process -Force
    .\deploy-mt5.ps1
#>

param(
    [Parameter()]
    [switch]$SkipSSHFix,    # 跳过 SSH 修复（已手动修复时使用）
    [Parameter()]
    [switch]$SystemOnly,     # 仅部署系统账户服务 (8001)
    [Parameter()]
    [switch]$UserOnly        # 仅部署用户账户服务 (8002)
)

$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"

# ─── 颜色输出辅助 ────────────────────────────────────────────────────────────
function Log-Info  { param($msg) Write-Host "[INFO]  $msg" -ForegroundColor Cyan   }
function Log-OK    { param($msg) Write-Host "[OK]    $msg" -ForegroundColor Green  }
function Log-Warn  { param($msg) Write-Host "[WARN]  $msg" -ForegroundColor Yellow }
function Log-Error { param($msg) Write-Host "[ERROR] $msg" -ForegroundColor Red    }

# ─── 1. 修复 OpenSSH 密码认证 ───────────────────────────────────────────────
if (-not $SkipSSHFix) {
    Log-Info "修复 OpenSSH sshd_config password auth..."

    $sshdConf = "C:\ProgramData\ssh\sshd_config"

    if (Test-Path $sshdConf) {
        $content = Get-Content $sshdConf

        # 启用密码认证
        $content = $content -replace "^#?\s*PasswordAuthentication\s+\w.*$",   "PasswordAuthentication yes"
        # 禁用公钥认证对 Administrator 的特殊 Match 块（AWS 默认会强制 key-only）
        $content = $content -replace "^#?\s*PubkeyAuthentication\s+no.*$",      "PubkeyAuthentication yes"
        # 注释掉 Match Group administrators 块（覆盖密码设置的罪魁祸首）
        $content = $content -replace "^Match Group administrators",              "# Match Group administrators"
        $content = $content -replace "^\s+AuthorizedKeysFile __PROGRAMDATA__",  "# AuthorizedKeysFile __PROGRAMDATA__"

        Set-Content $sshdConf $content -Encoding UTF8
        Log-OK "sshd_config 更新完成"

        Restart-Service sshd -Force
        Start-Sleep -Seconds 2
        $sshdStatus = (Get-Service sshd).Status
        Log-OK "sshd 状态: $sshdStatus"
    } else {
        Log-Warn "sshd_config 不存在，跳过 SSH 修复"
    }
}

# ─── 2. 检查 Python ────────────────────────────────────────────────────────
Log-Info "检查 Python 安装..."
$pythonCmd = $null
foreach ($candidate in @("python", "python3", "py")) {
    try {
        $ver = & $candidate --version 2>&1
        if ($ver -match "Python 3\.") {
            $pythonCmd = $candidate
            Log-OK "找到 Python: $ver ($candidate)"
            break
        }
    } catch { }
}

if (-not $pythonCmd) {
    Log-Warn "未找到 Python 3，正在从 python.org 下载 3.11..."
    $pyInstaller = "$env:TEMP\python-3.11.9-amd64.exe"
    Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" `
                      -OutFile $pyInstaller
    Start-Process -FilePath $pyInstaller -ArgumentList "/passive InstallAllUsers=1 PrependPath=1 Include_pip=1" -Wait
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + $env:Path
    $pythonCmd = "python"
    Log-OK "Python 3.11 安装完成"
}

# ─── 3. NSSM 服务管理器 ──────────────────────────────────────────────────────
Log-Info "检查 NSSM..."
$nssmPath = "C:\nssm\nssm.exe"
if (-not (Test-Path $nssmPath)) {
    Log-Info "下载 NSSM..."
    $nssmZip = "$env:TEMP\nssm.zip"
    Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile $nssmZip
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory($nssmZip, "C:\nssm-extract")

    # 解压的目录名含版本号，找 win64 下的 nssm.exe
    $nssmExe = Get-ChildItem -Path "C:\nssm-extract" -Recurse -Filter "nssm.exe" |
               Where-Object { $_.DirectoryName -like "*win64*" } |
               Select-Object -First 1

    if (-not $nssmExe) {
        $nssmExe = Get-ChildItem -Path "C:\nssm-extract" -Recurse -Filter "nssm.exe" |
                   Select-Object -First 1
    }

    New-Item -ItemType Directory -Path "C:\nssm" -Force | Out-Null
    Copy-Item $nssmExe.FullName $nssmPath
    Remove-Item "C:\nssm-extract" -Recurse -Force
    Log-OK "NSSM 已安装: $nssmPath"
} else {
    Log-OK "NSSM 已存在"
}

# ─── 辅助函数：部署单个服务实例 ─────────────────────────────────────────────
function Deploy-MT5Service {
    param(
        [string]$DeployDir,      # 部署目标目录 (D:\hustle-mt5)
        [string]$EnvFile,        # .env 文件路径（源）
        [string]$ServiceName,    # Windows 服务名
        [int]   $Port            # 监听端口
    )

    Log-Info "======================================================"
    Log-Info "部署 [$ServiceName] → $DeployDir (port $Port)"
    Log-Info "======================================================"

    # 3.1 创建目录并复制代码
    New-Item -ItemType Directory -Path "$DeployDir\app" -Force | Out-Null
    $scriptRoot = Split-Path -Parent $MyInvocation.ScriptName
    Copy-Item -Path "$scriptRoot\app\main.py"       -Destination "$DeployDir\app\main.py"       -Force
    Copy-Item -Path "$scriptRoot\requirements.txt"  -Destination "$DeployDir\requirements.txt"  -Force
    Copy-Item -Path $EnvFile                         -Destination "$DeployDir\.env"              -Force
    Log-OK "代码文件复制完成 → $DeployDir"

    # 3.2 创建虚拟环境
    $venvDir = "$DeployDir\venv"
    if (-not (Test-Path "$venvDir\Scripts\activate.ps1")) {
        Log-Info "创建虚拟环境..."
        & $pythonCmd -m venv $venvDir
    } else {
        Log-OK "虚拟环境已存在"
    }

    # 3.3 安装依赖
    Log-Info "安装 Python 依赖..."
    & "$venvDir\Scripts\pip.exe" install --upgrade pip -q
    & "$venvDir\Scripts\pip.exe" install -r "$DeployDir\requirements.txt" -q
    Log-OK "依赖安装完成"

    # 3.4 防火墙规则
    $fwRuleName = "MT5Bridge-$Port"
    $existing = Get-NetFirewallRule -DisplayName $fwRuleName -ErrorAction SilentlyContinue
    if (-not $existing) {
        New-NetFirewallRule -DisplayName $fwRuleName `
                            -Direction Inbound `
                            -Protocol TCP `
                            -LocalPort $Port `
                            -Action Allow `
                            -Profile Any | Out-Null
        Log-OK "防火墙入站端口 $Port 已开放"
    } else {
        Log-OK "防火墙规则已存在"
    }

    # 3.5 注册 Windows 服务（NSSM）
    $uvicornExe = "$venvDir\Scripts\uvicorn.exe"
    $appArgs    = "main:app --host 0.0.0.0 --port $Port"

    # 停止并删除旧服务（如存在）
    $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($svc) {
        Log-Warn "服务 $ServiceName 已存在，先停止删除..."
        & $nssmPath stop $ServiceName confirm 2>$null
        & $nssmPath remove $ServiceName confirm 2>$null
        Start-Sleep -Seconds 2
    }

    Log-Info "注册 Windows 服务 $ServiceName ..."
    & $nssmPath install $ServiceName $uvicornExe $appArgs
    & $nssmPath set $ServiceName AppDirectory "$DeployDir\app"
    & $nssmPath set $ServiceName AppEnvironmentExtra "PYTHONUNBUFFERED=1"
    & $nssmPath set $ServiceName Start SERVICE_AUTO_START
    & $nssmPath set $ServiceName AppStdout "$DeployDir\logs\stdout.log"
    & $nssmPath set $ServiceName AppStderr "$DeployDir\logs\stderr.log"
    & $nssmPath set $ServiceName AppRotateFiles 1
    & $nssmPath set $ServiceName AppRotateOnline 1
    & $nssmPath set $ServiceName AppRotateSeconds 86400
    & $nssmPath set $ServiceName AppRotateBytes 10485760

    # 日志目录
    New-Item -ItemType Directory -Path "$DeployDir\logs" -Force | Out-Null

    # 启动服务
    Start-Sleep -Seconds 1
    & $nssmPath start $ServiceName
    Start-Sleep -Seconds 4

    $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -eq "Running") {
        Log-OK "服务 $ServiceName 运行中 ✓"
    } else {
        Log-Warn "服务状态: $($svc.Status) — 请检查日志 $DeployDir\logs\stderr.log"
    }

    # 3.6 本机健康检查
    Start-Sleep -Seconds 3
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:$Port/health" -TimeoutSec 10 -UseBasicParsing
        Log-OK "健康检查通过: $($resp.Content)"
    } catch {
        Log-Warn "健康检查失败 (服务可能还在启动中): $_"
    }
}

# ─── 4. 执行部署 ─────────────────────────────────────────────────────────────
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition

if (-not $UserOnly) {
    Deploy-MT5Service `
        -DeployDir   "D:\hustle-mt5" `
        -EnvFile     "$scriptDir\.env.system" `
        -ServiceName "hustle-mt5-system" `
        -Port         8001
}

if (-not $SystemOnly) {
    $cq987Env = "$scriptDir\.env.cq987"
    if (Test-Path $cq987Env) {
        # 检查 cq987 .env 是否已填写真实账号
        $envContent = Get-Content $cq987Env -Raw
        if ($envContent -match "<cq987的MT5账号>") {
            Log-Warn ".env.cq987 尚未填写 cq987 账号，跳过用户服务部署"
            Log-Warn "请先编辑 $cq987Env 填入真实 MT5_LOGIN 和 MT5_PASSWORD"
        } else {
            Deploy-MT5Service `
                -DeployDir   "D:\hustle-mt5-cq987" `
                -EnvFile     $cq987Env `
                -ServiceName "hustle-mt5-cq987" `
                -Port         8002
        }
    } else {
        Log-Warn ".env.cq987 不存在，跳过用户服务部署"
    }
}

# ─── 5. 汇总 ─────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "======================================================" -ForegroundColor Magenta
Write-Host "  Hustle2026 MT5 Bridge 部署完成" -ForegroundColor Magenta
Write-Host "======================================================" -ForegroundColor Magenta
Write-Host ""
Write-Host "  系统账户服务 (8001): http://localhost:8001/health"
Write-Host "  用户cq987服务(8002): http://localhost:8002/health"
Write-Host ""
Write-Host "  服务管理命令:"
Write-Host "    启动: Start-Service hustle-mt5-system"
Write-Host "    停止: Stop-Service  hustle-mt5-system"
Write-Host "    日志: Get-Content D:\hustle-mt5\logs\stderr.log -Tail 50 -Wait"
Write-Host ""
Write-Host "  SSH 连接（修复后）:"
Write-Host "    ssh Administrator@54.249.66.53"
Write-Host ""
