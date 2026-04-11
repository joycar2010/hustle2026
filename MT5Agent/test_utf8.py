import subprocess

result = subprocess.run(
    ['nssm', 'start', 'hustle-mt5-cq987'],
    capture_output=True,
    encoding='utf-8',
    errors='replace',
    timeout=10
)

message = (result.stdout or result.stderr or "").strip()

print(f"returncode: {result.returncode}")
print(f"message length: {len(message)}")

# Check for keywords
test1 = "running" in message.lower()
test2 = "instance" in message.lower()
test3 = "实例" in message
test4 = "运行" in message

print(f"Test 1 - running: {test1}")
print(f"Test 2 - instance: {test2}")
print(f"Test 3 - Chinese 实例: {test3}")
print(f"Test 4 - Chinese 运行: {test4}")

already_running = result.returncode == 1 and (test1 or test2 or test3 or test4)
print(f"already_running: {already_running}")
print(f"success: {result.returncode == 0 or already_running}")
