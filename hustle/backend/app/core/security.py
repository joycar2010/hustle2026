from cryptography.fernet import Fernet
import os
from dotenv import load_dotenv
from .config import settings

load_dotenv()

# 获取加密密钥，优先从环境变量获取，否则从settings获取，最后生成新密钥
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY") or settings.ENCRYPTION_KEY
if not ENCRYPTION_KEY:
    # 生成新的加密密钥
    ENCRYPTION_KEY = Fernet.generate_key().decode()
    print(f"Generated new encryption key: {ENCRYPTION_KEY}")
    print("Please add this to your .env file as ENCRYPTION_KEY")

cipher_suite = Fernet(ENCRYPTION_KEY.encode())

def encrypt_data(data: str) -> str:
    """加密敏感数据"""
    if not data:
        return data
    encrypted = cipher_suite.encrypt(data.encode())
    return encrypted.decode()

def decrypt_data(data: str) -> str:
    """解密敏感数据"""
    if not data:
        return data
    decrypted = cipher_suite.decrypt(data.encode())
    return decrypted.decode()
