Set WshShell = CreateObject("WScript.Shell")

' 1. Start Hustle2026 Services
Set lnk1 = WshShell.CreateShortcut("C:\Users\Administrator\Desktop\Start Hustle2026 Services.lnk")
lnk1.TargetPath = "C:\app\hustle2026\start_services.bat"
lnk1.WorkingDirectory = "C:\app\hustle2026"
lnk1.Description = "启动 Hustle2026 全部服务 (Nginx + MT5 + Backend)"
lnk1.Save

' 2. Fix Hustle2026 Backend
Set lnk2 = WshShell.CreateShortcut("C:\Users\Administrator\Desktop\Fix Hustle2026 Backend.lnk")
lnk2.TargetPath = "C:\app\hustle2026\fix_backend.bat"
lnk2.WorkingDirectory = "C:\app\hustle2026"
lnk2.Description = "修复后端服务 (清理端口占用并重启)"
lnk2.Save

' 3. Check Services
Set lnk3 = WshShell.CreateShortcut("C:\Users\Administrator\Desktop\Check Hustle2026 Services.lnk")
lnk3.TargetPath = "C:\app\hustle2026\check_services.bat"
lnk3.WorkingDirectory = "C:\app\hustle2026"
lnk3.Description = "检查所有服务运行状态"
lnk3.Save

WScript.Echo "Shortcuts updated OK"
