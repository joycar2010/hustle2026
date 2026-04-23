import subprocess

result = subprocess.run(
    ['nssm', 'start', 'hustle-mt5-cq987'],
    capture_output=True,
    encoding='gbk',
    errors='replace',
    timeout=10
)

message = (result.stdout or result.stderr or "").strip()

# Print character codes from position 20
for i in range(20, min(len(message), 45)):
    char = message[i]
    print(f"{i}: U+{ord(char):04X} ({char if ord(char) < 128 else 'CJK'})")
