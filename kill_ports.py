import psutil
import sys

def kill_port_processes(port):
    """Kill all processes listening on the specified port"""
    killed = []
    failed = []

    for conn in psutil.net_connections():
        if conn.laddr.port == port and conn.status == 'LISTEN':
            try:
                process = psutil.Process(conn.pid)
                process_name = process.name()
                print(f"Killing process {conn.pid} ({process_name}) on port {port}")
                process.kill()
                process.wait(timeout=3)
                killed.append(conn.pid)
            except psutil.NoSuchProcess:
                print(f"Process {conn.pid} already dead")
            except psutil.AccessDenied:
                failed.append(conn.pid)
                print(f"Access denied for process {conn.pid}")
            except Exception as e:
                failed.append(conn.pid)
                print(f"Failed to kill process {conn.pid}: {e}")

    return killed, failed

if __name__ == "__main__":
    print("Cleaning ports 8000 and 3000...")

    # Kill port 8000
    killed_8000, failed_8000 = kill_port_processes(8000)
    print(f"\nPort 8000: Killed {len(killed_8000)} processes, Failed {len(failed_8000)} processes")

    # Kill port 3000
    killed_3000, failed_3000 = kill_port_processes(3000)
    print(f"Port 3000: Killed {len(killed_3000)} processes, Failed {len(failed_3000)} processes")

    if failed_8000 or failed_3000:
        print("\nSome processes could not be killed. You may need to run this script as administrator.")
        sys.exit(1)
    else:
        print("\nAll processes killed successfully!")
        sys.exit(0)
