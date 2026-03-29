"""Test GitHub versions API path calculation"""
import os

# Simulate the path calculation in system.py
current_file = os.path.abspath(__file__)
print(f"Current file: {current_file}")

# Go up levels
api_v1_dir = os.path.dirname(current_file)
print(f"API v1 dir: {api_v1_dir}")

api_dir = os.path.dirname(api_v1_dir)
print(f"API dir: {api_dir}")

app_dir = os.path.dirname(api_dir)
print(f"App dir: {app_dir}")

backend_dir = os.path.dirname(app_dir)
print(f"Backend dir: {backend_dir}")

project_root = os.path.dirname(backend_dir)
print(f"Project root: {project_root}")

print(f"\nProject root exists: {os.path.exists(project_root)}")
print(f"Is git repo: {os.path.exists(os.path.join(project_root, '.git'))}")
