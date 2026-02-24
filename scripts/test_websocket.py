#!/usr/bin/env python3
"""
WebSocket连接验证脚本
用途：测试WebSocket服务器连接、鉴权、消息推送功能
作者：系统架构团队
版本：1.0.0
"""

import asyncio
import websockets
import json
import sys
from datetime import datetime


class WebSocketTester:
    """WebSocket连接测试器"""

    def __init__(self, ws_url: str, token: str = None):
        self.ws_url = ws_url
        self.token = token
        self.connection_success = False
        self.messages_received = []
        self.errors = []

    async def test_connection(self, timeout: int = 10):
        """测试WebSocket连接"""
        print(f"[*] 测试WebSocket连接: {self.ws_url}")
        print(f"[*] 超时时间: {timeout}秒")
        print()

        # 构建连接URL
        url = self.ws_url
        if self.token:
            url = f"{self.ws_url}?token={self.token}"
            print(f"[*] 使用Token鉴权")
        else:
            print(f"[!] 警告: 未提供Token，可能无法通过鉴权")

        print()

        try:
            async with websockets.connect(url, ping_interval=None) as websocket:
                self.connection_success = True
                print(f"[+] WebSocket连接成功!")
                print(f"[*] 连接状态: {websocket.state.name}")
                print()

                # 监听消息
                print(f"[*] 开始监听消息 (持续{timeout}秒)...")
                print()

                try:
                    async with asyncio.timeout(timeout):
                        while True:
                            message = await websocket.recv()
                            self.messages_received.append(message)

                            # 解析消息
                            try:
                                msg_data = json.loads(message)
                                msg_type = msg_data.get('type', 'unknown')
                                timestamp = datetime.now().strftime("%H:%M:%S")

                                print(f"[{timestamp}] 收到消息类型: {msg_type}")

                                # 显示消息内容摘要
                                if msg_type == 'market_data':
                                    data = msg_data.get('data', {})
                                    print(f"  - Binance Bid: {data.get('binance_bid', 'N/A')}")
                                    print(f"  - Bybit Bid: {data.get('bybit_bid', 'N/A')}")
                                elif msg_type == 'risk_alert':
                                    alert = msg_data.get('alert', {})
                                    print(f"  - 警报: {alert.get('message', 'N/A')}")
                                elif msg_type == 'order_update':
                                    order = msg_data.get('order', {})
                                    print(f"  - 订单ID: {order.get('order_id', 'N/A')}")
                                else:
                                    print(f"  - 数据: {json.dumps(msg_data, ensure_ascii=False)[:100]}...")

                                print()

                            except json.JSONDecodeError:
                                print(f"[!] 无法解析消息: {message[:100]}...")
                                print()

                except asyncio.TimeoutError:
                    print(f"[*] 监听超时 ({timeout}秒)")
                    print()

        except websockets.exceptions.InvalidStatusCode as e:
            self.errors.append(f"连接失败 - HTTP状态码: {e.status_code}")
            print(f"[-] 连接失败: HTTP {e.status_code}")
            if e.status_code == 401:
                print(f"[!] 鉴权失败: Token无效或已过期")
            elif e.status_code == 403:
                print(f"[!] 权限不足: 无权访问WebSocket")
            print()

        except websockets.exceptions.InvalidURI as e:
            self.errors.append(f"无效的WebSocket URL: {e}")
            print(f"[-] 无效的WebSocket URL: {e}")
            print()

        except ConnectionRefusedError:
            self.errors.append("连接被拒绝 - 服务器未启动或端口不可达")
            print(f"[-] 连接被拒绝")
            print(f"[!] 可能原因:")
            print(f"    1. WebSocket服务器未启动")
            print(f"    2. 端口被防火墙阻止")
            print(f"    3. 服务器地址或端口错误")
            print()

        except OSError as e:
            self.errors.append(f"网络错误: {e}")
            print(f"[-] 网络错误: {e}")
            print()

        except Exception as e:
            self.errors.append(f"未知错误: {e}")
            print(f"[-] 未知错误: {e}")
            print()

    def generate_report(self):
        """生成测试报告"""
        print("=" * 60)
        print("WebSocket连接测试报告")
        print("=" * 60)
        print()

        print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"WebSocket URL: {self.ws_url}")
        print(f"使用Token: {'是' if self.token else '否'}")
        print()

        print("测试结果:")
        print("-" * 60)

        if self.connection_success:
            print(f"✅ 连接状态: 成功")
            print(f"✅ 收到消息数: {len(self.messages_received)}")

            if len(self.messages_received) > 0:
                print(f"✅ 消息推送: 正常")

                # 统计消息类型
                msg_types = {}
                for msg in self.messages_received:
                    try:
                        msg_data = json.loads(msg)
                        msg_type = msg_data.get('type', 'unknown')
                        msg_types[msg_type] = msg_types.get(msg_type, 0) + 1
                    except:
                        pass

                if msg_types:
                    print()
                    print("消息类型统计:")
                    for msg_type, count in msg_types.items():
                        print(f"  - {msg_type}: {count}条")
            else:
                print(f"⚠️  消息推送: 未收到任何消息")
                print(f"    可能原因:")
                print(f"    1. 后端推送服务未启动")
                print(f"    2. 没有可推送的数据")
                print(f"    3. 推送频率较低")
        else:
            print(f"❌ 连接状态: 失败")

            if self.errors:
                print()
                print("错误详情:")
                for error in self.errors:
                    print(f"  - {error}")

        print()
        print("=" * 60)

        return self.connection_success and len(self.messages_received) > 0


async def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='WebSocket连接验证工具')
    parser.add_argument('--url', default='ws://13.115.21.77:8000/ws', help='WebSocket URL')
    parser.add_argument('--token', help='JWT Token (可选)')
    parser.add_argument('--timeout', type=int, default=10, help='监听超时时间(秒)')

    args = parser.parse_args()

    # 创建测试器
    tester = WebSocketTester(args.url, args.token)

    # 执行测试
    await tester.test_connection(timeout=args.timeout)

    # 生成报告
    success = tester.generate_report()

    # 返回退出码
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print()
        print("[!] 测试被用户中断")
        sys.exit(1)
