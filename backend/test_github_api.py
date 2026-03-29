"""Test GitHub versions API"""
import subprocess
import os

# Get the project root directory
backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
project_root = os.path.dirname(backend_dir)

print(f"Backend dir: {backend_dir}")
print(f"Project root: {project_root}")
print(f"Project root exists: {os.path.exists(project_root)}")
print(f"Is git repo: {os.path.exists(os.path.join(project_root, '.git'))}")

# Test git fetch
print("\nTesting git fetch...")
fetch_result = subprocess.run(
    ["git", "fetch", "origin", "main"],
    capture_output=True,
    text=True,
    cwd=project_root
)
print(f"Fetch return code: {fetch_result.returncode}")
print(f"Fetch stdout: {fetch_result.stdout}")
print(f"Fetch stderr: {fetch_result.stderr}")

# Test git log
print("\nTesting git log...")
result = subprocess.run(
    ["git", "log", "origin/main", "--pretty=format:%H|%an|%ae|%ad|%s", "--date=format:%Y-%m-%d %H:%M:%S", "-5"],
    capture_output=True,
    text=True,
    encoding='utf-8',
    errors='replace',
    cwd=project_root
)
print(f"Log return code: {result.returncode}")
print(f"Log stdout:\n{result.stdout}")
print(f"Log stderr: {result.stderr}")
