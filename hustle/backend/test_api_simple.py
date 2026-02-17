import socket
import json

# 测试添加账户
print("测试添加账户...")
try:
    # 创建一个TCP连接
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    sock.connect(("localhost", 8000))
    
    # 构建HTTP请求
    data = {
        "platform_id": 1,
        "account_name": "test_account_4",
        "api_key": "test_api_key_4",
        "api_secret": "test_api_secret_4",
        "is_active": True
    }
    json_data = json.dumps(data)
    
    request = f"""
POST /api/v1/accounts HTTP/1.1
Host: localhost:8000
Content-Type: application/json
Content-Length: {len(json_data)}

{json_data}
"""
    
    # 发送请求
    sock.sendall(request.encode())
    
    # 接收响应
    response = sock.recv(4096).decode()
    print(f"添加账户响应:\n{response}")
    
    sock.close()

    print("测试完成！")
except Exception as e:
    print(f"错误: {e}")
    if 'sock' in locals():
        sock.close()