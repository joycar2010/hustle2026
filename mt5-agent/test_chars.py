import subprocess

result = subprocess.run(
    ['nssm', 'start', 'hustle-mt5-cq987'],
    capture_output=True,
    encoding='gbk',
    errors='replace',
    timeout=10
)

message = (result.stdout or result.stderr or "").strip()

# Print character codes
for i, char in enumerate(message):
    print(f"{i}: U+{ord(char):04X}")
    if i > 20:
        break
