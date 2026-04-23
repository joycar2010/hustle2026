import subprocess

result = subprocess.run(
    ['nssm', 'start', 'hustle-mt5-cq987'],
    capture_output=True,
    encoding='gbk',
    errors='replace',
    timeout=10
)

stdout = (result.stdout or "").strip()
stderr = (result.stderr or "").strip()
message = stdout or stderr or "Operation completed"

print(f"returncode: {result.returncode}")
print(f"message: {repr(message)}")
print(f"message bytes: {message.encode('utf-8')}")

message_lower = message.lower()
print(f"Test 1 - 'running' in message_lower: {'running' in message_lower}")
print(f"Test 2 - 'instance' in message_lower: {'instance' in message_lower}")
print(f"Test 3 - Unicode escape \u5b9e\u4f8b: {chr(0x5b9e) + chr(0x4f8b) in message}")
print(f"Test 4 - Direct Chinese: {'实例' in message}")

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
