import os
import glob

# 搜索可能的 MT5 安装路径
search_paths = [
    "C:\\Program Files\\*MT5*\\terminal64.exe",
    "C:\\Program Files (x86)\\*MT5*\\terminal64.exe",
    "C:\\Program Files\\Bybit*\\terminal64.exe",
    "C:\\Program Files (x86)\\Bybit*\\terminal64.exe",
    "C:\\Users\\*\\AppData\\Roaming\\MetaQuotes\\Terminal\\*\\terminal64.exe"
]

print("Searching for MT5 installations...")
for pattern in search_paths:
    matches = glob.glob(pattern)
    if matches:
        for match in matches:
            print(f"Found: {match}")
            print(f"  Exists: {os.path.exists(match)}")
