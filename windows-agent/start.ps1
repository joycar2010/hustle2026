# MT5 Windows Agent 启动脚本
Set-Location "C:\MT5Agent"
Start-Process -FilePath "python" -ArgumentList "main.py" -NoNewWindow -Wait
