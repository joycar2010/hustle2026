"""诊断点差提醒未触发的原因"""
import sys
import io
from sqlalchemy import create_engine, text
from app.core.config import settings
from datetime import datetime, timedelta

# Force UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

engine = create_engine(settings.DATABASE_URL)

print("=" * 80)
print("点差提醒诊断报告")
print("=" * 80)
print()

with engine.connect() as conn:
    # 1. 检查当前点差数据
    print("【1】当前点差数据")
    print("-" * 80)
    result = conn.execute(text('''
        SELECT forward_spread, reverse_spread, binance_bid, binance_ask,
               bybit_bid, bybit_ask, timestamp
        FROM spread_records
        ORDER BY timestamp DESC
        LIMIT 5
    ''')).fetchall()

    latest = None
    if result:
        print(f"最近5条点差记录：")
        for i, row in enumerate(result, 1):
            print(f"  {i}. Forward: {row[0]:.4f}, Reverse: {row[1]:.4f}")
            print(f"     Binance Bid/Ask: {row[2]:.2f}/{row[3]:.2f}")
            print(f"     Bybit Bid/Ask: {row[4]:.2f}/{row[5]:.2f}")
            print(f"     时间: {row[6]}")

        latest = result[0]
        print(f"\n当前点差值：")
        print(f"  Forward Spread: {latest[0]:.4f}")
        print(f"  Reverse Spread: {latest[1]:.4f}")
    else:
        print("❌ 没有点差数据！")
    print()

    # 2. 检查用户风险设置
    print("【2】用户风险设置")
    print("-" * 80)
    result = conn.execute(text('''
        SELECT u.username, u.user_id,
               rs.forward_open_price, rs.forward_close_price,
               rs.reverse_open_price, rs.reverse_close_price
        FROM users u
        LEFT JOIN risk_settings rs ON u.user_id = rs.user_id
        WHERE rs.forward_open_price IS NOT NULL
        ORDER BY u.username
    ''')).fetchall()

    if result:
        for row in result:
            print(f"用户: {row[0]} ({row[1]})")
            print(f"  正向开仓阈值: {row[2]}")
            print(f"  正向平仓阈值: {row[3]}")
            print(f"  反向开仓阈值: {row[4]}")
            print(f"  反向平仓阈值: {row[5]}")

            # 检查是否满足触发条件
            if latest:
                forward_spread = abs(latest[0])
                reverse_spread = abs(latest[1])

                print(f"\n  触发条件检查：")
                if forward_spread >= row[2]:
                    print(f"    ✓ 正向开仓: {forward_spread:.4f} >= {row[2]} (满足)")
                else:
                    print(f"    ✗ 正向开仓: {forward_spread:.4f} < {row[2]} (不满足)")

                if forward_spread <= row[3]:
                    print(f"    ✓ 正向平仓: {forward_spread:.4f} <= {row[3]} (满足)")
                else:
                    print(f"    ✗ 正向平仓: {forward_spread:.4f} > {row[3]} (不满足)")

                if reverse_spread >= row[4]:
                    print(f"    ✓ 反向开仓: {reverse_spread:.4f} >= {row[4]} (满足)")
                else:
                    print(f"    ✗ 反向开仓: {reverse_spread:.4f} < {row[4]} (不满足)")

                if reverse_spread <= row[5]:
                    print(f"    ✓ 反向平仓: {reverse_spread:.4f} <= {row[5]} (满足)")
                else:
                    print(f"    ✗ 反向平仓: {reverse_spread:.4f} > {row[5]} (不满足)")
            print()
    else:
        print("❌ 没有配置风险设置的用户！")
    print()

    # 3. 检查点差提醒模板
    print("【3】点差提醒模板状态")
    print("-" * 80)
    result = conn.execute(text('''
        SELECT template_key, template_name, is_active, enable_feishu
        FROM notification_templates
        WHERE template_key LIKE '%spread%'
        ORDER BY template_key
    ''')).fetchall()

    if result:
        for row in result:
            status = "✓ 激活" if row[2] else "✗ 未激活"
            feishu = "✓ 启用" if row[3] else "✗ 未启用"
            print(f"{row[0]}: {status}, 飞书: {feishu}")
    else:
        print("❌ 没有点差提醒模板！")
    print()

    # 4. 检查最近的通知日志
    print("【4】最近的点差通知日志")
    print("-" * 80)
    result = conn.execute(text('''
        SELECT template_key, status, sent_at, error_message, recipient
        FROM notification_logs
        WHERE template_key LIKE '%spread%'
        ORDER BY created_at DESC
        LIMIT 10
    ''')).fetchall()

    if result:
        print(f"最近10条点差通知记录：")
        for i, row in enumerate(result, 1):
            print(f"  {i}. {row[0]}")
            print(f"     状态: {row[1]}, 时间: {row[2]}")
            print(f"     接收者: {row[4]}")
            if row[3]:
                print(f"     错误: {row[3]}")
    else:
        print("❌ 没有点差通知日志！这可能是问题所在。")
    print()

    # 5. 检查所有通知日志（最近1小时）
    print("【5】最近1小时所有通知日志")
    print("-" * 80)
    one_hour_ago = datetime.now() - timedelta(hours=1)
    result = conn.execute(text('''
        SELECT template_key, status, sent_at, COUNT(*) as count
        FROM notification_logs
        WHERE created_at >= :time_threshold
        GROUP BY template_key, status, sent_at
        ORDER BY sent_at DESC
        LIMIT 20
    '''), {'time_threshold': one_hour_ago}).fetchall()

    if result:
        print(f"最近1小时通知统计：")
        for row in result:
            print(f"  {row[0]}: {row[1]} (数量: {row[3]}, 时间: {row[2]})")
    else:
        print("❌ 最近1小时没有任何通知日志！")
        print("   可能原因：")
        print("   1. 后台任务未运行")
        print("   2. 风险检查逻辑未执行")
        print("   3. 所有条件都不满足")
    print()

    # 6. 检查飞书服务配置
    print("【6】飞书服务配置")
    print("-" * 80)
    try:
        result = conn.execute(text('''
            SELECT service_name, is_enabled, webhook_url
            FROM notification_services
            WHERE service_name = 'feishu'
        ''')).fetchone()

        if result:
            print(f"服务名称: {result[0]}")
            print(f"启用状态: {'✓ 已启用' if result[1] else '✗ 未启用'}")
            print(f"Webhook URL: {result[2][:50]}..." if result[2] else "未配置")
        else:
            print("❌ 飞书服务未配置！")
    except Exception as e:
        print(f"⚠ 无法查询飞书服务配置（表可能不存在）: {e}")
    print()

print("=" * 80)
print("诊断建议")
print("=" * 80)
print("""
如果没有触发通知，可能的原因：

1. 点差数据不满足触发条件
   - 检查当前点差值是否达到阈值
   - 检查是否使用了绝对值比较

2. 后台任务未运行
   - 检查 AccountBalanceStreamer 是否启动
   - 查看后台日志: tail -f backend/logs/app.log

3. 冷却时间限制
   - 5秒内不会重复发送同类型通知
   - 检查 last_alert_time 缓存

4. 飞书服务问题
   - 检查飞书服务是否启用
   - 检查 webhook URL 是否正确
   - 检查网络连接

5. 模板配置问题
   - 检查模板是否激活
   - 检查飞书通知是否启用

6. 用户配置问题
   - 检查用户是否配置了风险设置
   - 检查阈值是否合理
""")
