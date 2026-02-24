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
