#!/bin/bash
# 全面检查页面刷新机制

echo "========== 页面刷新机制全面检查 =========="
echo ""

echo "1. 检查直接刷新方法..."
grep -r "window.location.reload\|location.reload" src/ --include="*.vue" --include="*.js" --include="*.ts" -n 2>/dev/null
if [ $? -ne 0 ]; then
    echo "   ✅ 未发现 location.reload()"
fi
echo ""

echo "2. 检查路由强制刷新..."
grep -r "router.go(0)" src/ --include="*.vue" --include="*.js" --include="*.ts" -n 2>/dev/null
if [ $? -ne 0 ]; then
    echo "   ✅ 未发现 router.go(0)"
fi
echo ""

echo "3. 检查位置跳转..."
grep -r "window.location\s*=\|location.href\s*=" src/ --include="*.vue" --include="*.js" --include="*.ts" -n 2>/dev/null
if [ $? -ne 0 ]; then
    echo "   ✅ 未发现 location 赋值"
fi
echo ""

echo "4. 检查 meta refresh..."
grep -r "http-equiv.*refresh" src/ public/ --include="*.html" --include="*.vue" -n 2>/dev/null
if [ $? -ne 0 ]; then
    echo "   ✅ 未发现 meta refresh"
fi
echo ""

echo "5. 检查所有 setInterval（可能导致频繁更新）..."
grep -r "setInterval" src/ --include="*.vue" --include="*.js" --include="*.ts" -n | grep -v "node_modules"
echo ""

echo "6. 检查 watch 监听（可能导致频繁重渲染）..."
grep -r "watch(" src/views/ src/components/trading/ --include="*.vue" -n | head -20
echo ""

echo "7. 检查 WebSocket 消息处理..."
grep -r "ws.onmessage\|onmessage" src/ --include="*.vue" --include="*.js" -n
echo ""

echo "8. 检查路由守卫..."
grep -r "router.beforeEach\|router.afterEach" src/ --include="*.js" --include="*.ts" -n
echo ""

echo "========== 检查完成 =========="
