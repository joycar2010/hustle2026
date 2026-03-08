#!/bin/bash
# 测试通知模板API

echo "=== 测试通知模板API ==="
echo ""

# 获取token（需要先登录）
echo "1. 测试获取模板列表（需要认证）"
curl -s -X GET "http://localhost:8000/api/v1/notifications/templates" \
  -H "Content-Type: application/json" | python -m json.tool | head -20

echo ""
echo "如果看到 'Not authenticated' 错误，这是正常的，因为需要登录token"
echo ""
echo "请在浏览器中："
echo "1. 打开开发者工具（F12）"
echo "2. 进入 Console 标签"
echo "3. 输入以下命令查看是否有日志输出："
echo ""
echo "   console.log('测试日志')"
echo ""
echo "4. 然后编辑一个模板并保存，查看控制台输出"
