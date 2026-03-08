import os
import subprocess

# Kill processes on port 8000
pids = [6864, 16708, 17004]

for pid in pids:
    try:
        subprocess.run(['taskkill', '/F', '/PID', str(pid)],
                      capture_output=True, text=True, check=False)
        print(f"Killed process {pid}")
    except Exception as e:
        print(f"Error killing {pid}: {e}")

# Wait a bit
import time
time.sleep(2)

# Check if any processes are still running
result = subprocess.run(['netstat', '-ano'], capture_output=True, text=True)
if ':8000' in result.stdout and 'LISTENING' in result.stdout:
    print("\nProcesses still running on port 8000:")
    for line in result.stdout.split('\n'):
        if ':8000' in line and 'LISTENING' in line:
            print(line)
else:
    print("\nPort 8000 is now free")

# Start backend
print("\nStarting backend...")
os.chdir('C:/app/hustle2026/backend')
subprocess.Popen(['python', '-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', '8000', '--reload'],
                 creationflags=subprocess.CREATE_NEW_CONSOLE)
print("Backend started in new console")
