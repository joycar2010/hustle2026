#!/usr/bin/env python3
"""
P1.3 QH端实施脚本
添加_get_tick_with_fallback函数到app.py
"""

def add_tick_fallback_to_app():
    print("=== 读取app.py ===")
    with open('/opt/quanthedge/app.py', 'r') as f:
        lines = f.readlines()

    print(f"总行数: {len(lines)}")

    # 找到cmd_open_pair函数位置
    cmd_open_pair_line = None
    for i, line in enumerate(lines):
        if 'async def cmd_open_pair(r:OpenPairReq):' in line:
            cmd_open_pair_line = i
            print(f"找到cmd_open_pair在第{i + 1}行")
            break

    if cmd_open_pair_line is None:
        print("错误: 找不到cmd_open_pair")
        return False

    # 在cmd_open_pair之前插入_get_tick_with_fallback函数
    tick_fallback_function = '''
# === P1.3: 行情快照优先读取 ===
async def _get_tick_with_fallback(leg, symbol, max_age_ms=500):
    """
    优先从Redis读取tick快照,过期则实时查询

    Args:
        leg: _BridgeLeg实例
        symbol: 币种,如"XAUUSD"
        max_age_ms: 最大允许的快照年龄(毫秒)

    Returns:
        tick字典或None
    """
    from datetime import datetime

    try:
        # 确定bridge_id (从leg的base URL判断)
        if 'main' in str(leg.base) or ':8041' in str(leg.base):
            bridge_id = 'main'
        elif 'hedge' in str(leg.base) or ':8042' in str(leg.base):
            bridge_id = 'hedge'
        else:
            bridge_id = 'main'  # 默认

        key = f"bridge:{bridge_id}:tick:{symbol}"
        snapshot = R.hgetall(key)

        if snapshot:
            # 检查快照年龄
            pushed_at = snapshot.get('pushed_at')
            if pushed_at:
                try:
                    pushed_time = datetime.fromisoformat(pushed_at.replace('Z', '+00:00'))
                    age_ms = (datetime.utcnow() - pushed_time.replace(tzinfo=None)).total_seconds() * 1000

                    if age_ms < max_age_ms:
                        # 快照新鲜,直接返回
                        return {
                            'symbol': snapshot.get('symbol'),
                            'bid': float(snapshot.get('bid', 0)),
                            'ask': float(snapshot.get('ask', 0)),
                            'time': int(snapshot.get('time', 0)),
                            'from_cache': True,
                            'age_ms': age_ms
                        }
                except Exception:
                    pass  # 时间解析失败,回退到实时查询
    except Exception:
        pass  # Redis读取失败,回退到实时查询

    # 快照不存在或过期,回退到实时查询
    try:
        tick = await leg._get(f"/mt5/tick/{symbol}")
        if tick:
            tick['from_cache'] = False
            tick['age_ms'] = 0
        return tick
    except Exception:
        return None

'''

    # 在cmd_open_pair前插入
    lines.insert(cmd_open_pair_line, tick_fallback_function)
    print(f"✓ 在第{cmd_open_pair_line + 1}行插入_get_tick_with_fallback函数")

    # 现在修改cmd_open_pair中的_tick_pair实现
    # 找到_tick_pair内联函数定义
    for i in range(cmd_open_pair_line, cmd_open_pair_line + 100):
        if i < len(lines) and 'async def _tick_pair():' in lines[i]:
            print(f"找到_tick_pair定义在第{i + 1}行")

            # 找到内部的one函数定义
            for j in range(i, i + 10):
                if j < len(lines) and 'async def one(leg,sym):' in lines[j]:
                    # 修改one函数使用_get_tick_with_fallback
                    # 原: try: return await leg._get("/mt5/tick/"+sym)
                    # 改: try: return await _get_tick_with_fallback(leg, sym)

                    for k in range(j, j + 5):
                        if k < len(lines) and 'return await leg._get("/mt5/tick/"' in lines[k]:
                            lines[k] = lines[k].replace(
                                'return await leg._get("/mt5/tick/"+sym)',
                                'return await _get_tick_with_fallback(leg, sym, max_age_ms=500)'
                            )
                            print(f"✓ 修改第{k + 1}行使用_get_tick_with_fallback")
                            break
                    break
            break

    # 保存
    with open('/opt/quanthedge/app.py', 'w') as f:
        f.writelines(lines)

    print("✓ 修改完成")
    return True

if __name__ == '__main__':
    import sys
    success = add_tick_fallback_to_app()
    sys.exit(0 if success else 1)
