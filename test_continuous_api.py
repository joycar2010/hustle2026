#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试连续执行API"""
import requests
import json
import sys
import io

# 设置UTF-8编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def test_continuous_api():
    print("=" * 80)
    print("测试连续执行API")
    print("=" * 80)

    # 准备请求数据
    url = "http://localhost:8000/api/v1/strategies/execute/forward/continuous"

    payload = {
        "binance_account_id": "c3b7d20d-787a-4bdd-9f92-d73716630bcf",
        "bybit_account_id": "1ce0146d-b2cb-467d-8b34-ff951e696563",
        "opening_m_coin": 2.0,
        "closing_m_coin": 2.0,
        "trigger_check_interval": 0.05,
        "ladders": [
            {
                "enabled": True,
                "opening_spread": 2.0,  # 降低阈值以便测试
                "closing_spread": 1.0,
                "total_qty": 2.0,
                "opening_trigger_count": 2,
                "closing_trigger_count": 1
            }
        ]
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer test_token"  # 需要替换为真实token
    }

    print(f"\n发送请求到: {url}")
    print(f"请求数据: {json.dumps(payload, indent=2, ensure_ascii=False)}")

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)

        print(f"\n响应状态码: {response.status_code}")
        print(f"响应内容: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")

        if response.status_code == 200:
            data = response.json()
            if data.get('task_id'):
                print(f"\n✓ 任务创建成功！")
                print(f"Task ID: {data['task_id']}")
                print(f"Strategy ID: {data.get('strategy_id')}")

                # 等待几秒后检查状态
                import time
                time.sleep(3)

                # 检查任务状态
                status_url = f"http://localhost:8000/api/v1/strategies/execution/{data['task_id']}/status"
                print(f"\n检查任务状态: {status_url}")
                status_response = requests.get(status_url, headers=headers)
                print(f"状态响应: {json.dumps(status_response.json(), indent=2, ensure_ascii=False)}")
            else:
                print("\n✗ 响应中没有task_id")
        else:
            print(f"\n✗ 请求失败: {response.text}")

    except requests.exceptions.RequestException as e:
        print(f"\n✗ 请求异常: {e}")
    except Exception as e:
        print(f"\n✗ 错误: {e}")

    print("\n" + "=" * 80)

if __name__ == "__main__":
    test_continuous_api()
