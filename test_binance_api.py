#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Binance API 测试脚本
测试现货和合约账户的各项数据获取功能
"""

import hmac
import hashlib
import time
import requests
import sys
import io
from datetime import datetime, timedelta
from urllib.parse import urlencode

# 设置UTF-8编码输出
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# API 配置
API_KEY = 'DLtsEW0Ei6EVKE6lxlQqsoQ2SGMqcXoWrx97CFB9gVckp8PF87iFxF3URW9S3NSI'
SECRET_KEY = 'fqqLLpgecb2Wb1AsHhx1zxUeNCU1nAKg21k9xnZuETyRJBNRxFuyK99TtAgnCbhp'
SPOT_BASE_URL = 'https://api.binance.com'
FUTURES_BASE_URL = 'https://fapi.binance.com'


def generate_signature(query_string):
    """生成签名"""
    return hmac.new(
        SECRET_KEY.encode('utf-8'),
        query_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()


def make_request(base_url, endpoint, params=None, needs_signature=True):
    """通用请求函数"""
    if params is None:
        params = {}

    headers = {'X-MBX-APIKEY': API_KEY}

    if needs_signature:
        params['timestamp'] = int(time.time() * 1000)
        query_string = urlencode(params)
        params['signature'] = generate_signature(query_string)

    url = f"{base_url}{endpoint}"

    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"❌ 请求失败: {e}")
        if hasattr(e.response, 'text'):
            print(f"   响应内容: {e.response.text}")
        return None


def test_spot_account():
    """测试现货账户"""
    print("\n" + "="*60)
    print("1. 测试现货账户 (/api/v3/account)")
    print("="*60)

    data = make_request(SPOT_BASE_URL, '/api/v3/account')
    if data:
        print("✅ 成功获取现货账户信息")
        print(f"   账户类型: {data.get('accountType')}")
        print(f"   是否可交易: {data.get('canTrade')}")
        print(f"   资产数量: {len(data.get('balances', []))}")

        # 显示有余额的资产
        balances = [b for b in data.get('balances', [])
                   if float(b['free']) > 0 or float(b['locked']) > 0]
        if balances:
            print(f"\n   有余额的资产 ({len(balances)} 个):")
            for balance in balances[:10]:  # 只显示前10个
                print(f"   - {balance['asset']}: "
                      f"可用={balance['free']}, 冻结={balance['locked']}")

    return data


def test_prices():
    """测试价格信息"""
    print("\n" + "="*60)
    print("2. 测试价格信息 (/api/v3/ticker/price)")
    print("="*60)

    data = make_request(SPOT_BASE_URL, '/api/v3/ticker/price', needs_signature=False)
    if data:
        print(f"✅ 成功获取价格信息，共 {len(data)} 个交易对")

        # 显示部分USDT交易对价格
        usdt_pairs = [p for p in data if p['symbol'].endswith('USDT')][:10]
        print(f"\n   部分USDT交易对价格:")
        for pair in usdt_pairs:
            print(f"   - {pair['symbol']}: {pair['price']}")

    return data


def test_futures_account():
    """测试合约账户"""
    print("\n" + "="*60)
    print("3. 测试合约账户 (/fapi/v2/account)")
    print("="*60)

    data = make_request(FUTURES_BASE_URL, '/fapi/v2/account')
    if data:
        print("✅ 成功获取合约账户信息")
        print(f"   账户权益: {data.get('totalWalletBalance')} USDT")
        print(f"   可用余额: {data.get('availableBalance')} USDT")
        print(f"   保证金余额: {data.get('totalMarginBalance')} USDT")
        print(f"   未实现盈亏: {data.get('totalUnrealizedProfit')} USDT")
        print(f"   维持保证金: {data.get('totalMaintMargin')} USDT")

        # 显示有余额的资产
        assets = [a for a in data.get('assets', [])
                 if float(a.get('walletBalance', 0)) > 0]
        if assets:
            print(f"\n   有余额的资产 ({len(assets)} 个):")
            for asset in assets:
                print(f"   - {asset['asset']}: "
                      f"余额={asset['walletBalance']}, "
                      f"可用={asset['availableBalance']}")

    return data


def test_position_risk():
    """测试持仓风险"""
    print("\n" + "="*60)
    print("4. 测试持仓风险 (/fapi/v1/positionRisk)")
    print("="*60)

    data = make_request(FUTURES_BASE_URL, '/fapi/v1/positionRisk',
                       {'marginAsset': 'USDT'})
    if data:
        # 过滤出有持仓的
        positions = [p for p in data if float(p.get('positionAmt', 0)) != 0]

        print(f"✅ 成功获取持仓信息，共 {len(positions)} 个持仓")

        if positions:
            print(f"\n   当前持仓:")
            for pos in positions:
                print(f"   - {pos['symbol']}: "
                      f"数量={pos['positionAmt']}, "
                      f"标记价格={pos['markPrice']}, "
                      f"未实现盈亏={pos['unRealizedProfit']}")
        else:
            print("   当前无持仓")

    return data


def test_income():
    """测试收益历史"""
    print("\n" + "="*60)
    print("5. 测试收益历史 (/fapi/v1/income)")
    print("="*60)

    # 获取今日开始时间戳
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_time = int(today.timestamp() * 1000)

    data = make_request(FUTURES_BASE_URL, '/fapi/v1/income', {
        'incomeType': 'REALIZED_PNL',
        'startTime': start_time
    })

    if data:
        print(f"✅ 成功获取收益历史，共 {len(data)} 条记录")

        # 计算总盈亏
        total_pnl = sum(float(item['income']) for item in data)
        print(f"   当日已实现盈亏: {total_pnl:.4f} USDT")

        if data:
            print(f"\n   最近的收益记录:")
            for item in data[:5]:  # 只显示前5条
                dt = datetime.fromtimestamp(item['time'] / 1000)
                print(f"   - {dt.strftime('%H:%M:%S')} "
                      f"{item['symbol']}: {item['income']} USDT")

    return data


def test_funding_fee():
    """测试资金费率"""
    print("\n" + "="*60)
    print("6. 测试资金费率 (/fapi/v1/fundingFee)")
    print("="*60)

    # 获取今日开始时间戳
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_time = int(today.timestamp() * 1000)

    data = make_request(FUTURES_BASE_URL, '/fapi/v1/fundingFee', {
        'startTime': start_time
    })

    if data:
        print(f"✅ 成功获取资金费率，共 {len(data)} 条记录")

        # 计算总资金费
        total_fee = sum(float(item['income']) for item in data)
        print(f"   当日资金费总计: {total_fee:.4f} USDT")

        if data:
            print(f"\n   最近的资金费记录:")
            for item in data[:5]:  # 只显示前5条
                dt = datetime.fromtimestamp(item['time'] / 1000)
                print(f"   - {dt.strftime('%H:%M:%S')} "
                      f"{item['symbol']}: {item['income']} USDT")

    return data


def calculate_summary():
    """计算汇总数据"""
    print("\n" + "="*60)
    print("📊 汇总计算")
    print("="*60)

    # 获取所有数据
    spot_account = make_request(SPOT_BASE_URL, '/api/v3/account')
    prices = make_request(SPOT_BASE_URL, '/api/v3/ticker/price', needs_signature=False)
    futures_account = make_request(FUTURES_BASE_URL, '/fapi/v2/account')
    position_risk = make_request(FUTURES_BASE_URL, '/fapi/v1/positionRisk',
                                {'marginAsset': 'USDT'})

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_time = int(today.timestamp() * 1000)

    income = make_request(FUTURES_BASE_URL, '/fapi/v1/income', {
        'incomeType': 'REALIZED_PNL',
        'startTime': start_time
    })

    funding_fee = make_request(FUTURES_BASE_URL, '/fapi/v1/fundingFee', {
        'startTime': start_time
    })

    if not all([spot_account, prices, futures_account, position_risk]):
        print("❌ 无法获取完整数据，跳过汇总计算")
        return

    # 创建价格映射
    price_map = {p['symbol']: float(p['price']) for p in prices}

    # 计算现货资产（转换为USDT）
    spot_total = 0
    spot_available = 0
    spot_frozen = 0

    for balance in spot_account.get('balances', []):
        free = float(balance['free'])
        locked = float(balance['locked'])

        if free > 0 or locked > 0:
            if balance['asset'] == 'USDT':
                usdt_value = 1
            else:
                symbol = balance['asset'] + 'USDT'
                usdt_value = price_map.get(symbol, 0)

            spot_total += (free + locked) * usdt_value
            spot_available += free * usdt_value
            spot_frozen += locked * usdt_value

    # 合约数据
    futures_equity = float(futures_account.get('totalWalletBalance', 0))
    futures_available = float(futures_account.get('availableBalance', 0))
    futures_margin = float(futures_account.get('totalMarginBalance', 0))
    futures_frozen = futures_margin - futures_available

    # 总持仓
    total_positions = 0
    for pos in position_risk:
        position_amt = abs(float(pos.get('positionAmt', 0)))
        mark_price = float(pos.get('markPrice', 0))
        total_positions += position_amt * mark_price

    # 当日盈亏
    daily_pnl = sum(float(item['income']) for item in (income or []))

    # 掉期费
    total_funding_fee = sum(float(item['income']) for item in (funding_fee or []))

    # 风险率
    maint_margin = float(futures_account.get('totalMaintMargin', 0))
    risk_ratio = (maint_margin / futures_margin * 100) if futures_margin > 0 else 0

    # 显示汇总结果
    print("\n汇总计算完成:\n")
    print(f"账户总资产: {spot_total + futures_equity:.2f} USDT")
    print(f"   ├─ 现货资产: {spot_total:.2f} USDT")
    print(f"   └─ 合约权益: {futures_equity:.2f} USDT")
    print()
    print(f"可用总资产: {spot_available + futures_available:.2f} USDT")
    print(f"   ├─ 现货可用: {spot_available:.2f} USDT")
    print(f"   └─ 合约可用: {futures_available:.2f} USDT")
    print()
    print(f"冻结资产: {spot_frozen + futures_frozen:.2f} USDT")
    print(f"   ├─ 现货冻结: {spot_frozen:.2f} USDT")
    print(f"   └─ 合约冻结: {futures_frozen:.2f} USDT")
    print()
    print(f"总持仓: {total_positions:.2f} USDT")
    print(f"当日盈亏: {daily_pnl:.4f} USDT")
    print(f"保证金余额: {futures_margin:.2f} USDT")
    print(f"风险率: {risk_ratio:.2f}%")
    print(f"掉期费: {total_funding_fee:.4f} USDT")


def main():
    """主函数"""
    print("="*60)
    print("Binance API 测试脚本")
    print("="*60)
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        # 依次测试各个端点
        test_spot_account()
        time.sleep(0.5)

        test_prices()
        time.sleep(0.5)

        test_futures_account()
        time.sleep(0.5)

        test_position_risk()
        time.sleep(0.5)

        test_income()
        time.sleep(0.5)

        test_funding_fee()
        time.sleep(0.5)

        # 计算汇总
        calculate_summary()

        print("\n" + "="*60)
        print("所有测试完成")
        print("="*60)

    except KeyboardInterrupt:
        print("\n\n测试被用户中断")
    except Exception as e:
        print(f"\n\n测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
