#!/usr/bin/env bash
# =============================================================================
# hustle-go-patch 完整部署脚本
# 执行位置：服务器 (ubuntu@go.hustle2026.xyz)
# 命令：bash /tmp/deploy.sh
# =============================================================================
set -e
GO_SRC="/home/ubuntu/hustle-go"
PATCH_BASE="/tmp/hustle-go-patch"

echo "=== [1/7] 备份当前 hustle-go 二进制 ==="
sudo cp "$GO_SRC/hustle-go" "$GO_SRC/hustle-go.bak.$(date +%Y%m%d-%H%M%S)" 2>/dev/null || true

echo "=== [2/7] 合并 patch 文件到 hustle-go 源码 ==="
# accounts handler
cp "$PATCH_BASE/accounts/handler.go" "$GO_SRC/internal/accounts/handler.go"
# monitor handler
cp "$PATCH_BASE/monitor/handler.go" "$GO_SRC/internal/monitor/handler.go"
# opportunities handler
cp "$PATCH_BASE/opportunities/handler.go" "$GO_SRC/internal/opportunities/handler.go"

echo "=== [3/7] 注册新路由到 main.go ==="
# 检查 opportunities 路由是否已注册，若无则追加
grep -q '"hustle-go/internal/opportunities"' "$GO_SRC/cmd/server/main.go" && \
    echo "  opportunities 路由已注册，跳过" || \
    python3 - <<'PYEOF'
import re, sys

main_path = "/home/ubuntu/hustle-go/cmd/server/main.go"
with open(main_path, "r") as f:
    src = f.read()

# Add import
if '"hustle-go/internal/opportunities"' not in src:
    src = src.replace(
        '"hustle-go/internal/monitor"',
        '"hustle-go/internal/monitor"\n\t"hustle-go/internal/opportunities"'
    )
    print("  Added opportunities import")

# Add routes (after monitor routes block)
opp_routes = '''
	// Opportunities
	opp := v1.Group("/opportunities", middleware.JWTAuth())
	opp.GET("", opportunities.List)
	opp.GET("/stats", opportunities.Stats)
	opp.POST("/extract", opportunities.Extract)
	opp.POST("/cleanup", opportunities.Cleanup)
'''

if 'opportunities.List' not in src:
    # Insert before sysops wildcard
    src = src.replace(
        '\tv1.GET("/monitor/status"',
        opp_routes + '\tv1.GET("/monitor/status"'
    )
    print("  Added opportunities routes")

with open(main_path, "w") as f:
    f.write(src)
print("  main.go updated")
PYEOF

# 检查 monitor/ssl/current 路由是否已注册
grep -q 'monitor/ssl/current\|SSLCurrent' "$GO_SRC/cmd/server/main.go" && \
    echo "  ssl/current 路由已注册，跳过" || \
    python3 - <<'PYEOF'
main_path = "/home/ubuntu/hustle-go/cmd/server/main.go"
with open(main_path, "r") as f:
    src = f.read()

if 'SSLCurrent' not in src:
    src = src.replace(
        'v1.GET("/monitor/status", monitor.Status)',
        'v1.GET("/monitor/status", monitor.Status)\n\tv1.GET("/monitor/ssl/current", monitor.SSLCurrent)'
    )
    print("  Added SSLCurrent route")
    with open(main_path, "w") as f:
        f.write(src)
PYEOF

echo "=== [4/7] 编译 ==="
cd "$GO_SRC"
go build -o hustle-go-new ./cmd/server/

echo "=== [5/7] 重启 hustle-go 服务 ==="
sudo systemctl stop hustle-go
mv hustle-go hustle-go.prev
mv hustle-go-new hustle-go
sudo systemctl start hustle-go
sleep 2
sudo systemctl status hustle-go --no-pager | tail -8

echo "=== [6/7] 修复 nginx: users/me → Go:8080 ==="
NGINX_CONF="/etc/nginx/sites-enabled/hustle-go"
if grep -q "location = /api/v1/users/me" "$NGINX_CONF"; then
    # 将 users/me 的代理目标从 :8000 改为 :8080
    sudo sed -i \
        '/location = \/api\/v1\/users\/me/,/}/ s|proxy_pass http://127\.0\.0\.1:8000|proxy_pass http://127.0.0.1:8080|g' \
        "$NGINX_CONF"
    sudo nginx -t && sudo systemctl reload nginx
    echo "  nginx users/me 路由已修复 → Go:8080"
else
    echo "  ⚠️  未找到 users/me location block，请手动检查 nginx 配置"
fi

echo "=== [7/7] 验证关键端点 ==="
TOKEN=$(curl -sf -X POST https://go.hustle2026.xyz/api/v1/auth/login \
    -H "Content-Type: application/json" \
    -d '{"username":"admin","password":"Linxiaoyun2026!@"}' \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('access_token',''))" 2>/dev/null || echo "")

if [ -z "$TOKEN" ]; then
    echo "  ⚠️  无法获取 token，跳过验证"
else
    echo "  [monitor/status]"
    curl -sf -H "Authorization: Bearer $TOKEN" https://go.hustle2026.xyz/api/v1/monitor/status | python3 -c "import sys,json; d=json.load(sys.stdin); print('  OK: redis='+d['redis']['status'])" || echo "  FAIL"

    echo "  [monitor/ssl/current]"
    curl -sf -H "Authorization: Bearer $TOKEN" https://go.hustle2026.xyz/api/v1/monitor/ssl/current | python3 -c "import sys,json; d=json.load(sys.stdin); print('  OK: certs='+str(len(d.get('certificates',[]))))" || echo "  FAIL"

    echo "  [opportunities]"
    curl -sf -H "Authorization: Bearer $TOKEN" "https://go.hustle2026.xyz/api/v1/opportunities?limit=1" | python3 -c "import sys,json; d=json.load(sys.stdin); print('  OK: count='+str(len(d)))" || echo "  FAIL"

    echo "  [users/me]"
    curl -sf -H "Authorization: Bearer $TOKEN" https://go.hustle2026.xyz/api/v1/users/me | python3 -c "import sys,json; d=json.load(sys.stdin); print('  OK: user='+d.get('username','?'))" || echo "  FAIL"

    echo "  [accounts proxy_config]"
    curl -sf -H "Authorization: Bearer $TOKEN" https://go.hustle2026.xyz/api/v1/accounts | python3 -c "import sys,json; d=json.load(sys.stdin); print('  OK: accounts='+str(len(d))+', first_has_proxy_config='+str('proxy_config' in (d[0] if d else {})))" || echo "  FAIL"
fi

echo ""
echo "=== 部署完成 ==="
