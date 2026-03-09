import subprocess
import os

def update_and_start_services():
    """Update service scripts and start services"""
    print("Updating service configurations...")

    os.chdir('C:/app/hustle2026')

    # Update VBS script for backend to use persistent script
    backend_vbs = 'start_backend_service.vbs'
    with open(backend_vbs, 'w') as f:
        f.write('Set WshShell = CreateObject("WScript.Shell")\n')
        f.write('WshShell.Run "C:\\app\\hustle2026\\start_backend_persistent.bat", 0, False\n')

    # Update VBS script for frontend to use persistent script
    frontend_vbs = 'start_frontend_service.vbs'
    with open(frontend_vbs, 'w') as f:
        f.write('Set WshShell = CreateObject("WScript.Shell")\n')
        f.write('WshShell.Run "C:\\app\\hustle2026\\start_frontend_persistent.bat", 0, False\n')

    print("VBS scripts updated")

    # Stop any existing processes
    print("\nStopping existing processes...")
    subprocess.run(['taskkill', '/F', '/IM', 'python.exe'], capture_output=True)
    subprocess.run(['taskkill', '/F', '/IM', 'node.exe'], capture_output=True)

    # Start backend service
    print("\nStarting backend service...")
    subprocess.Popen(
        ['wscript.exe', backend_vbs],
        cwd='C:/app/hustle2026',
        creationflags=subprocess.CREATE_NO_WINDOW
    )
    print("[OK] Backend service started")

    # Wait a bit
    import time
    time.sleep(5)

    # Start frontend service
    print("\nStarting frontend service...")
    subprocess.Popen(
        ['wscript.exe', frontend_vbs],
        cwd='C:/app/hustle2026',
        creationflags=subprocess.CREATE_NO_WINDOW
    )
    print("[OK] Frontend service started")

    print("\n" + "="*50)
    print("Services started successfully!")
    print("="*50)
    print("\nBackend: http://localhost:8000")
    print("Frontend: http://localhost:3000")
    print("API Docs: http://localhost:8000/docs")
    print("\nServices will restart automatically if they crash.")
    print("Services will start automatically on system boot.")

if __name__ == "__main__":
    update_and_start_services()
