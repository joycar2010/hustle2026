@echo off
REM SSH Public Key Authorization Script
REM Run this on MT5 server (54.249.66.53) as Administrator

echo ========================================
echo SSH Public Key Authorization
echo ========================================
echo.

set SSH_DIR=C:\Users\Administrator\.ssh
set AUTH_KEYS=%SSH_DIR%\authorized_keys
set PUBLIC_KEY=ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMZnRHno9RCGHSI0hijpQP2HZp23c9PM958vFwy5wUrN HUAWEI@JoyBook

echo [1/4] Checking .ssh directory...
if not exist "%SSH_DIR%" (
    echo   Creating directory: %SSH_DIR%
    mkdir "%SSH_DIR%"
    echo   Done
) else (
    echo   Directory exists
)
echo.

echo [2/4] Checking authorized_keys file...
if not exist "%AUTH_KEYS%" (
    echo   Creating file: %AUTH_KEYS%
    type nul > "%AUTH_KEYS%"
    echo   Done
) else (
    echo   File exists
)
echo.

echo [3/4] Adding public key...
findstr /C:"%PUBLIC_KEY%" "%AUTH_KEYS%" >nul 2>&1
if %errorLevel% equ 0 (
    echo   Public key already exists
) else (
    echo %PUBLIC_KEY% >> "%AUTH_KEYS%"
    echo   Public key added
)
echo.

echo [4/4] Setting file permissions...
icacls "%AUTH_KEYS%" /inheritance:r
icacls "%AUTH_KEYS%" /grant:r Administrator:F
icacls "%AUTH_KEYS%" /grant:r SYSTEM:F
echo   Permissions set
echo.

echo ========================================
echo Authorization Complete!
echo ========================================
echo.
echo Public Key Info:
echo   Type: ED25519
echo   Source: HUAWEI@JoyBook
echo.
echo authorized_keys location:
echo   %AUTH_KEYS%
echo.
echo Test connection from local machine:
echo   ssh -i c:/Users/HUAWEI/.ssh/id_ed25519 Administrator@54.249.66.53
echo.
pause
