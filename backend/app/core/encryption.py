"""Encryption utilities for sensitive data"""
from cryptography.fernet import Fernet
from app.core.config import settings


class EncryptionService:
    """Service for encrypting and decrypting sensitive data"""

    def __init__(self):
        """Initialize encryption service with key from environment"""
        self._fernet = Fernet(settings.ENCRYPTION_KEY.encode())

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt plaintext string

        Args:
            plaintext: String to encrypt

        Returns:
            Encrypted string (base64 encoded)
        """
        if not plaintext:
            return ""

        encrypted_bytes = self._fernet.encrypt(plaintext.encode())
        return encrypted_bytes.decode()

    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt ciphertext string

        Args:
            ciphertext: Encrypted string (base64 encoded)

        Returns:
            Decrypted plaintext string
        """
        if not ciphertext:
            return ""

        decrypted_bytes = self._fernet.decrypt(ciphertext.encode())
        return decrypted_bytes.decode()


# Global encryption service instance
encryption_service = EncryptionService()


# Convenience functions for API key encryption
def encrypt_api_key(api_key: str) -> str:
    """
    Encrypt API key using Fernet encryption

    Args:
        api_key: Plain text API key

    Returns:
        Encrypted API key (base64 encoded)
    """
    return encryption_service.encrypt(api_key)


def decrypt_api_key(encrypted_key: str) -> str:
    """
    Decrypt API key using Fernet encryption

    Args:
        encrypted_key: Encrypted API key (base64 encoded)

    Returns:
        Decrypted plain text API key
    """
    return encryption_service.decrypt(encrypted_key)
