import subprocess

result = subprocess.run(
    ['nssm', 'start', 'hustle-mt5-cq987'],
    capture_output=True,
    text=True,
    timeout=10
)

stdout = (result.stdout or "").strip()
stderr = (result.stderr or "").strip()
message = stdout or stderr or "Operation completed"

print(f"returncode: {result.returncode}")
print(f"stdout: {repr(stdout)}")
print(f"stderr: {repr(stderr)}")
print(f"message: {repr(message)}")

message_lower = message.lower()
already_running = (
    result.returncode == 1 and (
        "running" in message_lower or
        "instance" in message_lower or
        "\u5b9e\u4f8b" in message or
        "\u8fd0\u884c" in message
    )
)

print(f"already_running: {already_running}")
print(f"success: {result.returncode == 0 or already_running}")
