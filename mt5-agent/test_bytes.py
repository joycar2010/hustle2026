import subprocess

result = subprocess.run(
    ['nssm', 'start', 'hustle-mt5-cq987'],
    capture_output=True,
    timeout=10
)

stdout_bytes = result.stdout or b''
stderr_bytes = result.stderr or b''

print(f"returncode: {result.returncode}")
print(f"stdout bytes: {stdout_bytes[:60]}")
print(f"stderr bytes: {stderr_bytes[:60]}")

# Try different encodings
for enc in ['utf-8', 'gbk', 'gb2312', 'cp936']:
    try:
        msg = (stdout_bytes or stderr_bytes).decode(enc, errors='replace').strip()
        has_match = "实例" in msg or "运行" in msg or "running" in msg.lower()
        print(f"{enc}: len={len(msg)}, match={has_match}")
    except:
        print(f"{enc}: failed")
