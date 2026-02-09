#!/usr/bin/env python3
"""
Hustle XAU点差对冲搬砖系统 - 依赖项安装脚本
"""

import subprocess
import sys

def install_packages():
    """安装所需的Python包"""
    packages = [
        'ccxt',
        'pybit',
        'pytz'
    ]
    
    print("开始安装依赖项...")
    
    for package in packages:
        try:
            print(f"安装 {package}...")
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', package])
            print(f"{package} 安装成功!")
        except subprocess.CalledProcessError as e:
            print(f"安装 {package} 失败: {e}")
            return False
    
    print("\n所有依赖项安装完成!")
    print("\n下一步:")
    print("1. 确保您已获取币安和Bybit的API Key")
    print("2. 在 arbitrage_system.py 文件中配置您的API Key")
    print("3. 调整策略参数（如最小点差、交易大小等）")
    print("4. 取消注释 system.run() 行以启动系统")
    
    return True

if __name__ == '__main__':
    install_packages()
