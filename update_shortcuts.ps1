$WshShell = New-Object -ComObject WScript.Shell

# 1. Start Hustle2026 Services
$lnk1 = $WshShell.CreateShortcut("C:\Users\Administrator\Desktop\Start Hustle2026 Services.lnk")
$lnk1.TargetPath = "C:\app\hustle2026\start_services.bat"
$lnk1.WorkingDirectory = "C:\app\hustle2026"
$lnk1.Description = "启动 Hustle2026 全部服务 (Nginx + MT5 + Backend)"
$lnk1.IconLocation = "C:\Windows\System32\shell32.dll,162"
$lnk1.Save()
# Set RunAsAdministrator flag
$bytes = [System.IO.File]::ReadAllBytes("C:\Users\Administrator\Desktop\Start Hustle2026 Services.lnk")
$bytes[0x15] = $bytes[0x15] -bor 0x20
[System.IO.File]::WriteAllBytes("C:\Users\Administrator\Desktop\Start Hustle2026 Services.lnk", $bytes)

# 2. Fix Hustle2026 Backend
$lnk2 = $WshShell.CreateShortcut("C:\Users\Administrator\Desktop\Fix Hustle2026 Backend.lnk")
$lnk2.TargetPath = "C:\app\hustle2026\fix_backend.bat"
$lnk2.WorkingDirectory = "C:\app\hustle2026"
$lnk2.Description = "修复后端服务 (清理端口占用并重启)"
$lnk2.IconLocation = "C:\Windows\System32\shell32.dll,84"
$lnk2.Save()
$bytes2 = [System.IO.File]::ReadAllBytes("C:\Users\Administrator\Desktop\Fix Hustle2026 Backend.lnk")
$bytes2[0x15] = $bytes2[0x15] -bor 0x20
[System.IO.File]::WriteAllBytes("C:\Users\Administrator\Desktop\Fix Hustle2026 Backend.lnk", $bytes2)

# 3. Check Services
$lnk3 = $WshShell.CreateShortcut("C:\Users\Administrator\Desktop\Check Hustle2026 Services.lnk")
$lnk3.TargetPath = "C:\app\hustle2026\check_services.bat"
$lnk3.WorkingDirectory = "C:\app\hustle2026"
$lnk3.Description = "检查所有服务运行状态"
$lnk3.IconLocation = "C:\Windows\System32\shell32.dll,23"
$lnk3.Save()

Write-Host "Desktop shortcuts updated successfully."
