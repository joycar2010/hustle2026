#!/bin/bash
# 更新 admin.hustle2026.xyz 的 nginx 配置

set -e

echo "=== 更新 admin.hustle2026.xyz nginx 配置 ==="

# 备份当前配置
BACKUP_FILE="/etc/nginx/sites-enabled/hustle-go.backup-$(date +%Y%m%d_%H%M%S)"
sudo cp /etc/nginx/sites-enabled/hustle-go "$BACKUP_FILE"
echo "✓ 备份创建: $BACKUP_FILE"

# 创建临时文件
TEMP_FILE=$(mktemp)

# 使用 Python 处理配置
sudo python3 << 'PYTHON_EOF' > "$TEMP_FILE"
import re

# Read current config
with open('/etc/nginx/sites-enabled/hustle-go', 'r') as f:
    content = f.read()

# Remove old admin.hustle2026.xyz server blocks (including comments)
# Match from "# admin.hustle2026.xyz" comment to the end of the second server block
pattern = r'# admin\.hustle2026\.xyz[^\n]*\n.*?server \{[^}]*\}.*?server \{[^}]*\}'
new_content = re.sub(pattern, '', content, flags=re.DOTALL)

# Read new admin config
with open('/home/ubuntu/hustle2026/nginx/admin.hustle2026.xyz.conf', 'r') as f:
    admin_config = f.read()

# Find the position before www.hustle2026.xyz
www_pos = new_content.find('# www.hustle2026.xyz')
if www_pos > 0:
    # Insert new admin config before www
    new_content = new_content[:www_pos] + admin_config + '\n\n' + new_content[www_pos:]
else:
    # If www not found, append at the end
    new_content = new_content + '\n\n' + admin_config

print(new_content)
PYTHON_EOF

# 写入新配置
sudo cp "$TEMP_FILE" /etc/nginx/sites-enabled/hustle-go
rm "$TEMP_FILE"
echo "✓ 配置已更新"

# 测试配置
echo ""
echo "=== 测试 nginx 配置 ==="
sudo nginx -t

# 重载 nginx
echo ""
echo "=== 重载 nginx ==="
sudo systemctl reload nginx
echo "✓ nginx 已重载"

echo ""
echo "=== 完成 ==="
echo "admin.hustle2026.xyz 现在所有 /api/ 请求都代理到 Python 后端（端口 8000）"
