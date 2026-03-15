#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""检查连续执行触发状态"""
import requests
import json
import sys
import io

# 设置UTF-8编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def check_status():
    print("=" * 80)
    print("连续执行触发状态检查")
    print("=" * 80)

    # 获取当前市场点差
    try:
        response = requests.get("http://localhost:8000/api/v1/market/spread")
        data = response.json()

        print("\n当前市场点差:")
        print(f"  正向开仓点差 (forward_entry_spread): {data['forward_entry_spread']:.2f}")
        print(f"  正向平仓点差 (forward_exit_spread): {data['forward_exit_spread']:.2f}")
        print(f"  反向开仓点差 (reverse_entry_spread): {data['reverse_entry_spread']:.2f}")
        print(f"  反向平仓点差 (reverse_exit_spread): {data['reverse_exit_spread']:.2f}")

        # 从最近的API调用日志中读取配置
        with open("api_debug.log", "r") as f:
            lines = f.readlines()
            # 找到最后一次API调用
            for i in range(len(lines) - 1, -1, -1):
                if "Request:" in lines[i]:
                    # 提取配置信息
                    request_line = lines[i]
                    if "'opening_spread':" in request_line:
                        # 简单解析
                        import ast
                        try:
                            # 提取字典部分
                            dict_str = request_line.split("Request: ")[1].strip()
                            # 这里简化处理，直接查找数值
                            import re
                            opening_spread = re.search(r"'opening_spread': ([\d.]+)", dict_str)
                            trigger_count = re.search(r"'opening_trigger_count': (\d+)", dict_str)

                            if opening_spread and trigger_count:
                                threshold = float(opening_spread.group(1))
                                required_count = int(trigger_count.group(1))

                                print("\n用户配置:")
                                print(f"  开仓点差阈值: {threshold:.2f}")
                                print(f"  触发次数要求: {required_count}")

                                print("\n触发条件分析:")
                                current_spread = data['forward_entry_spread']
                                if current_spread >= threshold:
                                    print(f"  ✓ 点差满足条件: {current_spread:.2f} >= {threshold:.2f}")
                                    print(f"  → 系统会开始累积触发次数")
                                    print(f"  → 当触发次数达到 {required_count} 次时，会执行开仓")
                                else:
                                    print(f"  ✗ 点差不满足条件: {current_spread:.2f} < {threshold:.2f}")
                                    print(f"  → 系统正在等待点差达到 {threshold:.2f}")
                                    print(f"  → 需要点差上涨 {threshold - current_spread:.2f} 才能开始触发")

                                print("\n建议:")
                                if current_spread < threshold:
                                    print(f"  1. 等待市场点差上涨到 {threshold:.2f} 以上")
                                    print(f"  2. 或者降低开仓点差阈值到 {current_spread:.2f} 以下")
                                    print(f"  3. 当前点差与阈值差距: {threshold - current_spread:.2f}")
                        except Exception as e:
                            print(f"\n解析配置失败: {e}")
                    break

    except Exception as e:
        print(f"\n错误: {e}")

    print("\n" + "=" * 80)

if __name__ == "__main__":
    check_status()
