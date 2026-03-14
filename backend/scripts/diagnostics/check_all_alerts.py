"""检查所有风险控制提醒"""
import sys
import io
from sqlalchemy import create_engine, text
from app.core.config import settings
from datetime import datetime, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
engine = create_engine(settings.DATABASE_URL)

print('=' * 80)
print('风险控制提醒全面检查')
print('=' * 80)
print()

with engine.connect() as conn:
    # 1. 检查最近1小时所有提醒
    result = conn.execute(text('''
        SELECT template_key, COUNT(*) as count,
               SUM(CASE WHEN status = 'sent' THEN 1 ELSE 0 END) as success
        FROM notification_logs
        WHERE created_at >= :time_threshold
        GROUP BY template_key
        ORDER BY count DESC
    '''), {'time_threshold': datetime.now() - timedelta(hours=1)}).fetchall()

    print('【1】最近1小时提醒统计')
    print('-' * 80)
    if result:
        for row in result:
            print(f'  {row[0]}: {row[1]}条 (成功: {row[2]})')
    else:
        print('  ❌ 没有任何提醒记录')
    print()

    # 2. 检查所有激活的提醒模板
    result = conn.execute(text('''
        SELECT template_key, template_name, category, is_active, enable_feishu
        FROM notification_templates
        WHERE is_active = true
        ORDER BY category, template_key
    '')).fetchall()

    print('【2】所有激活的提醒模板')
    print('-' * 80)
    current_category = None
    for row in result:
        if row[2] != current_category:
            current_category = row[2]
            print(f'\n  [{row[2]}]')
        feishu_status = '✓' if row[4] else '✗'
        print(f'    • {row[0]}: {row[1]} (飞书: {feishu_status})')
    print()

    # 3. 检查用户风险设置
    result = conn.execute(text("""
        SELECT u.username,
               rs.binance_net_asset, rs.bybit_mt5_net_asset, rs.total_net_asset,
               rs.binance_liquidation_price, rs.bybit_mt5_liquidation_price,
               rs.mt5_lag_count,
               rs.forward_open_price, rs.forward_close_price,
               rs.reverse_open_price, rs.reverse_close_price
        FROM users u
        JOIN risk_settings rs ON u.user_id = rs.user_id
        WHERE u.username IN ('admin', 'cq987')
    """)).fetchall()

    print('【3】用户风险阈值配置')
    print('-' * 80)
    for row in result:
        print(f'\n  用户: {row[0]}')
        print(f'    净资产阈值:')
        print(f'      Binance: {row[1]}')
        print(f'      Bybit MT5: {row[2]}')
        print(f'      总净资产: {row[3]}')
        print(f'    爆仓价格阈值:')
        print(f'      Binance: {row[4]}')
        print(f'      Bybit MT5: {row[5]}')
        print(f'    MT5延迟阈值: {row[6]}')
        print(f'    点差阈值:')
        print(f'      正向开仓: {row[7]}, 正向平仓: {row[8]}')
        print(f'      反向开仓: {row[9]}, 反向平仓: {row[10]}')
    print()

print('=' * 80)
print('总结')
print('=' * 80)
print('检查要点:')
print('1. 点差提醒已触发')
print('2. 其他风险提醒需要满足阈值条件才会触发')
print('3. 前端弹窗需要WebSocket连接正常')

