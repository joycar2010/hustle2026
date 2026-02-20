"""
Check system prerequisites for Hustle XAU
"""
import sys
import subprocess
import socket


def check_command(command, name):
    """Check if a command is available"""
    try:
        result = subprocess.run(
            [command, "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            print(f"✓ {name} is installed")
            return True
        else:
            print(f"✗ {name} is not installed")
            return False
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print(f"✗ {name} is not installed")
        return False


def check_port(port, service):
    """Check if a port is open"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    result = sock.connect_ex(('localhost', port))
    sock.close()

    if result == 0:
        print(f"✓ {service} is running on port {port}")
        return True
    else:
        print(f"✗ {service} is not running on port {port}")
        return False


def main():
    print("=" * 50)
    print("Hustle XAU - System Prerequisites Check")
    print("=" * 50)
    print()

    # Check Python version
    print("Python Version:")
    version = sys.version_info
    if version.major == 3 and version.minor >= 9:
        print(f"✓ Python {version.major}.{version.minor}.{version.micro}")
    else:
        print(f"✗ Python {version.major}.{version.minor}.{version.micro} (requires 3.9+)")
    print()

    # Check commands
    print("Required Software:")
    python_ok = check_command("python", "Python")
    pip_ok = check_command("pip", "pip")
    node_ok = check_command("node", "Node.js")
    npm_ok = check_command("npm", "npm")
    print()

    # Check services
    print("Required Services:")
    postgres_ok = check_port(5432, "PostgreSQL")
    redis_ok = check_port(6379, "Redis")
    print()

    # Check backend ports
    print("Application Ports:")
    backend_free = not check_port(8000, "Backend (should be free)")
    frontend_free = not check_port(3000, "Frontend (should be free)")
    print()

    # Summary
    print("=" * 50)
    print("Summary:")
    print("=" * 50)

    all_ok = all([
        python_ok, pip_ok, node_ok, npm_ok,
        postgres_ok, redis_ok
    ])

    if all_ok:
        print("✓ All prerequisites are met!")
        print()
        print("Next steps:")
        print("  1. Run: cd backend && alembic upgrade head")
        print("  2. Run: python create_test_user.py")
        print("  3. Start backend: uvicorn app.main:app --reload")
        print("  4. Start frontend: cd ../frontend && npm run dev")
    else:
        print("✗ Some prerequisites are missing")
        print()
        print("Please install missing components:")

        if not postgres_ok:
            print("  - PostgreSQL: https://www.postgresql.org/download/")
        if not redis_ok:
            print("  - Redis: https://redis.io/download/")
        if not node_ok or not npm_ok:
            print("  - Node.js: https://nodejs.org/")

        print()
        print("After installation, run this script again.")


if __name__ == "__main__":
    main()
