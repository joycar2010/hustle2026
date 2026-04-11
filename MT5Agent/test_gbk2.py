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
print(f"message length: {len(message)}")

message_lower = message.lower()
test1 = "running" in message_lower
test2 = "instance" in message_lower
test3 = "\u5b9e\u4f8b" in message
test4 = "\u8fd0\u884c" in message

print(f"Test 1 - running: {test1}")
print(f"Test 2 - instance: {test2}")
print(f"Test 3 - Unicode 5b9e4f8b: {test3}")
print(f"Test 4 - Unicode 8fd0884c: {test4}")

already_running = (
    result.returncode == 1 and (test1 or test2 or test3 or test4)
)

print(f"already_running: {already_running}")
print(f"success: {result.returncode == 0 or already_running}")
