"""
直接修复 Windows Agent 的 stop_mt5_client 函数
"""
import re

# 读取原文件
with open(r'C:\MT5Agent\main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 新的函数实现
new_function = '''def stop_mt5_client(deploy_path: str, account: str = None) -> bool:
    """
    停止 MT5 客户端（只停止指定部署路径的实例）

    策略：
    1. 通过进程的工作目录（cwd）匹配部署路径
    2. 如果无法获取 cwd，通过命令行参数匹配
    3. 只停止匹配的进程，不影响其他实例
    """
    stopped = False
    terminal_procs = []
    deploy_path_normalized = Path(deploy_path).resolve()

    # 收集所有 terminal64 进程
    for proc in psutil.process_iter(['name', 'pid']):
        try:
            if proc.info['name'] and 'terminal64.exe' in proc.info['name'].lower():
                terminal_procs.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not terminal_procs:
        return False

    # 如果只有一个 MT5 进程，直接停止它
    if len(terminal_procs) == 1:
        try:
            terminal_procs[0].terminate()
            terminal_procs[0].wait(timeout=5)
            stopped = True
        except psutil.TimeoutExpired:
            terminal_procs[0].kill()
            stopped = True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return stopped

    # 多个进程：通过部署路径匹配
    target_proc = None

    for proc in terminal_procs:
        try:
            # 方法1：检查进程的工作目录
            try:
                proc_cwd = Path(proc.cwd()).resolve()
                if deploy_path_normalized in proc_cwd.parents or proc_cwd == deploy_path_normalized:
                    target_proc = proc
                    break
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass

            # 方法2：检查命令行参数
            try:
                cmdline = ' '.join(proc.cmdline())
                if str(deploy_path_normalized) in cmdline or deploy_path in cmdline:
                    target_proc = proc
                    break
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass

            # 方法3：检查打开的文件
            try:
                for file in proc.open_files():
                    file_path = Path(file.path).resolve()
                    if deploy_path_normalized in file_path.parents:
                        target_proc = proc
                        break
                if target_proc:
                    break
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # 停止匹配的进程
    if target_proc:
        try:
            target_proc.terminate()
            target_proc.wait(timeout=5)
            stopped = True
        except psutil.TimeoutExpired:
            target_proc.kill()
            stopped = True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    else:
        print(f"Warning: Could not identify MT5 process for deploy_path: {deploy_path}")
        print(f"Found {len(terminal_procs)} MT5 processes but none matched")
        stopped = False

    return stopped'''

# 查找并替换旧函数
pattern = r'def stop_mt5_client\(deploy_path: str, account: str = None\) -> bool:.*?(?=\ndef )'
new_content = re.sub(pattern, new_function + '\n\n', content, flags=re.DOTALL)

# 保存修改
with open(r'C:\MT5Agent\main.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Fix completed!")
print("Updated stop_mt5_client function")
print("Now only stops MT5 client at specified deploy path")
