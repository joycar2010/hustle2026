"""
完整的删除用户功能验证方案

环境：Python 3.10+ + SQLAlchemy 2.0 + PostgreSQL 14 + FastAPI
"""

# ============================================
# 步骤1：验证数据库结构
# ============================================
print("步骤1：验证数据库结构")
print("=" * 60)

# 运行数据库结构检查脚本
# cd /c/app/hustle2026/backend && python check_db_schema.py

# 预期输出：
# strategy_performance.strategy_id: integer (int4)
# 外键: strategy_id -> strategies.id

# ============================================
# 步骤2：验证模型定义
# ============================================
print("\n步骤2：验证模型定义")
print("=" * 60)

# 检查 StrategyPerformance 模型
# grep -n "strategy_id.*Column" app/models/strategy_performance.py

# 预期输出：
# strategy_id = Column(Integer, ForeignKey("strategies.id", ondelete="CASCADE"), ...)

# ============================================
# 步骤3：验证后端服务状态
# ============================================
print("\n步骤3：验证后端服务状态")
print("=" * 60)

import requests

try:
    response = requests.get("http://localhost:8001/health", timeout=5)
    print(f"✓ 后端服务状态: {response.json()}")
except Exception as e:
    print(f"✗ 后端服务异常: {e}")

# ============================================
# 步骤4：测试删除用户 API
# ============================================
print("\n步骤4：测试删除用户 API")
print("=" * 60)

# 4.1 登录获取 token
login_data = {
    "username": "admin",
    "password": "admin123"  # 替换为实际密码
}

try:
    login_response = requests.post(
        "http://localhost:8001/api/v1/auth/login",
        json=login_data,
        timeout=10
    )

    if login_response.status_code == 200:
        token = login_response.json().get("access_token")
        print(f"✓ 登录成功")

        # 4.2 获取用户列表
        headers = {"Authorization": f"Bearer {token}"}
        users_response = requests.get(
            "http://localhost:8001/api/v1/users/",
            headers=headers,
            timeout=10
        )

        if users_response.status_code == 200:
            users = users_response.json()
            print(f"✓ 获取用户列表成功，共 {len(users)} 个用户")

            # 找一个测试用户（非 admin）
            test_user = None
            for user in users:
                if user['username'] != 'admin':
                    test_user = user
                    break

            if test_user:
                print(f"\n测试用户: {test_user['username']} ({test_user['user_id']})")

                # 4.3 删除测试用户
                confirm = input("是否删除此用户？(yes/no): ")
                if confirm.lower() == 'yes':
                    delete_response = requests.delete(
                        f"http://localhost:8001/api/v1/users/{test_user['user_id']}",
                        headers=headers,
                        timeout=10
                    )

                    if delete_response.status_code == 204:
                        print("✓ 删除用户成功")
                    else:
                        print(f"✗ 删除失败: {delete_response.text}")
                else:
                    print("取消删除操作")
            else:
                print("没有找到可测试的用户")
        else:
            print(f"✗ 获取用户列表失败: {users_response.text}")
    else:
        print(f"✗ 登录失败: {login_response.text}")

except Exception as e:
    print(f"✗ 测试过程出错: {e}")

# ============================================
# 步骤5：数据库验证
# ============================================
print("\n步骤5：数据库验证")
print("=" * 60)
print("""
连接数据库并执行以下 SQL 验证：

-- 检查用户是否被删除
SELECT * FROM users WHERE user_id = '<deleted_user_id>';

-- 检查关联的策略是否被删除
SELECT * FROM strategies WHERE user_id = '<deleted_user_id>';

-- 检查关联的策略性能记录是否被删除
SELECT sp.* FROM strategy_performance sp
JOIN strategies s ON sp.strategy_id = s.id
WHERE s.user_id = '<deleted_user_id>';

-- 检查关联的策略配置是否被删除
SELECT * FROM strategy_configs WHERE user_id = '<deleted_user_id>';

预期结果：所有查询应返回 0 行
""")

# ============================================
# 步骤6：错误场景测试
# ============================================
print("\n步骤6：错误场景测试")
print("=" * 60)
print("""
测试以下错误场景：

1. 删除不存在的用户
   DELETE /api/v1/users/<invalid_uuid>
   预期: 404 Not Found

2. 非管理员删除用户
   使用普通用户 token 删除
   预期: 403 Forbidden

3. 删除自己的账户
   使用 admin token 删除 admin
   预期: 400 Bad Request

4. 未登录删除用户
   不提供 Authorization header
   预期: 401 Unauthorized
""")

print("\n" + "=" * 60)
print("验证完成！")
print("=" * 60)
