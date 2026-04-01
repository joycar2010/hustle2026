#!/bin/bash
# 部署 Windows Agent 到 Windows 服务器

echo "=== 部署 Windows Agent ==="

# 1. 复制文件到 Linux 服务器的临时目录
echo "1. 上传文件到 Linux 服务器..."
scp -i ~/.ssh/id_ed25519 windows-agent/main_v3.py ubuntu@go.hustle2026.xyz:/tmp/

# 2. 从 Linux 服务器复制到 Windows 服务器
echo "2. 从 Linux 服务器复制到 Windows 服务器..."
ssh -i ~/.ssh/id_ed25519 ubuntu@go.hustle2026.xyz << 'EOF'
# 使用 smbclient 或其他方式复制到 Windows
# 这里需要根据实际的 Windows 服务器访问方式调整
echo "请手动将 /tmp/main_v3.py 复制到 Windows 服务器"
echo "Windows 服务器地址: 172.31.14.113"
echo "目标路径: C:\\Users\\Administrator\\windows-agent\\main_v3.py"
EOF

echo "=== 部署完成 ==="
echo "请在 Windows 服务器上重启 Windows Agent 服务"
