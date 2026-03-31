"""
修复 MT5Agent 的 stop_mt5_client 函数
只停止指定部署路径的 MT5 客户端，不影响其他实例
"""

def stop_mt5_client(deploy_path: str, account: str = None) -> bool:
    """
    停止 MT5 客户端（只停止指定部署路径的实例）

    策略：
    1. 通过进程的工作目录（cwd）匹配部署路径
    2. 如果无法获取 cwd，通过命令行参数匹配
    3. 只停止匹配的进程，不影响其他实例

    Args:
        deploy_path: 部署目录路径
        account: MT5 账号（用于日志）

    Returns:
        是否成功停止
    """
    import psutil
    from pathlib import Path

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
                # 检查工作目录是否在部署路径下
                if deploy_path_normalized in proc_cwd.parents or proc_cwd == deploy_path_normalized:
                    target_proc = proc
                    break
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass

            # 方法2：检查命令行参数中是否包含部署路径
            try:
                cmdline = ' '.join(proc.cmdline())
                if str(deploy_path_normalized) in cmdline or deploy_path in cmdline:
                    target_proc = proc
                    break
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass

            # 方法3：检查进程打开的文件
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
        # 无法识别目标进程，记录警告但不停止任何进程
        # 避免误停止其他实例
        print(f"Warning: Could not identify MT5 process for deploy_path: {deploy_path}")
        print(f"Found {len(terminal_procs)} MT5 processes but none matched the deploy path")
        stopped = False

    return stopped
