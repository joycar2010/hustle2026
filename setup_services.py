import subprocess
import os
import time

def install_services():
    """Install backend and frontend services"""
    print("Installing services...")

    # Change to project directory
    os.chdir('C:/app/hustle2026')

    # Create VBS script for backend
    backend_vbs = 'start_backend_service.vbs'
    with open(backend_vbs, 'w') as f:
        f.write('Set WshShell = CreateObject("WScript.Shell")\n')
        f.write('WshShell.Run "C:\\app\\hustle2026\\start_backend.bat", 0, False\n')

    # Create VBS script for frontend
    frontend_vbs = 'start_frontend_service.vbs'
    with open(frontend_vbs, 'w') as f:
        f.write('Set WshShell = CreateObject("WScript.Shell")\n')
        f.write('WshShell.Run "C:\\app\\hustle2026\\start_frontend.bat", 0, False\n')

    print("VBS scripts created")

    # Install backend service
    print("\nInstalling backend service...")
    result = subprocess.run([
        'schtasks', '/create',
        '/tn', 'HustleBackendService',
        '/tr', f'C:\\app\\hustle2026\\{backend_vbs}',
        '/sc', 'onstart',
        '/ru', 'SYSTEM',
        '/rl', 'highest',
        '/f'
    ], capture_output=True, text=True)

    if result.returncode == 0:
        print("[OK] Backend service installed")
    else:
        print(f"[ERROR] Backend service installation failed: {result.stderr}")

    # Install frontend service (with 30 second delay)
    print("\nInstalling frontend service...")
    result = subprocess.run([
        'schtasks', '/create',
        '/tn', 'HustleFrontendService',
        '/tr', f'C:\\app\\hustle2026\\{frontend_vbs}',
        '/sc', 'onstart',
        '/ru', 'SYSTEM',
        '/rl', 'highest',
        '/delay', '0000:30',
        '/f'
    ], capture_output=True, text=True)

    if result.returncode == 0:
        print("[OK] Frontend service installed")
    else:
        print(f"[ERROR] Frontend service installation failed: {result.stderr}")

    print("\n" + "="*50)
    print("Services installed successfully!")
    print("="*50)

def start_services():
    """Start the services"""
    print("\nStarting services...")

    # Start backend service
    print("\n[1/2] Starting backend service...")
    result = subprocess.run([
        'schtasks', '/run', '/tn', 'HustleBackendService'
    ], capture_output=True, text=True)

    if result.returncode == 0:
        print("[OK] Backend service started")
    else:
        print(f"[ERROR] Failed to start backend: {result.stderr}")

    # Wait for backend to initialize
    print("\nWaiting 10 seconds for backend to initialize...")
    time.sleep(10)

    # Start frontend service
    print("\n[2/2] Starting frontend service...")
    result = subprocess.run([
        'schtasks', '/run', '/tn', 'HustleFrontendService'
    ], capture_output=True, text=True)

    if result.returncode == 0:
        print("[OK] Frontend service started")
    else:
        print(f"[ERROR] Failed to start frontend: {result.stderr}")

    print("\n" + "="*50)
    print("Services started!")
    print("="*50)
    print("\nBackend: http://localhost:8000")
    print("Frontend: http://localhost:3000")
    print("API Docs: http://localhost:8000/docs")

if __name__ == "__main__":
    install_services()
    start_services()
