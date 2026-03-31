"""
为 Windows Agent 添加进程检查端点
检查实际运行的 terminal64.exe 进程
"""

# 添加到 Windows Agent (C:\MT5Agent\main.py) 的新端点

NEW_ENDPOINT = '''
@app.get("/system/mt5-processes")
async def get_mt5_processes():
    """获取所有 MT5 terminal64.exe 进程"""
    import psutil
    from pathlib import Path

    processes = []

    for proc in psutil.process_iter(['pid', 'name', 'create_time']):
        try:
            if proc.info['name'] and 'terminal64.exe' in proc.info['name'].lower():
                # 获取进程详细信息
                try:
                    wmi_proc = None
                    import subprocess
                    result = subprocess.run(
                        ['wmic', 'process', 'where', f'ProcessId={proc.info["pid"]}',
                         'get', 'ExecutablePath,CommandLine', '/format:list'],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )

                    exe_path = ""
                    cmd_line = ""
                    for line in result.stdout.split('\\n'):
                        if line.startswith('ExecutablePath='):
                            exe_path = line.split('=', 1)[1].strip()
                        elif line.startswith('CommandLine='):
                            cmd_line = line.split('=', 1)[1].strip()

                    processes.append({
                        'pid': proc.info['pid'],
                        'name': proc.info['name'],
                        'exe_path': exe_path,
                        'cmd_line': cmd_line,
                        'create_time': proc.info['create_time'],
                        'memory_mb': round(proc.memory_info().rss / 1024 / 1024, 2)
                    })
                except Exception as e:
                    processes.append({
                        'pid': proc.info['pid'],
                        'name': proc.info['name'],
                        'error': str(e)
                    })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return {
        'count': len(processes),
        'processes': processes
    }
'''

print("新端点代码：")
print(NEW_ENDPOINT)
print("\n将此端点添加到 C:\\MT5Agent\\main.py 中")
