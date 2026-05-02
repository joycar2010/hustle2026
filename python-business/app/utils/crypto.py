import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings


def _get_key() -> bytes:
    key_hex = getattr(settings, 'encryption_key', None)
    if not key_hex:
        return None
    return bytes.fromhex(key_hex)


def encrypt(plaintext: str) -> str:
    key = _get_key()
    if not key:
        return plaintext
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, plaintext.encode('utf-8'), None)
    return base64.b64encode(nonce + ct).decode('ascii')


class DecryptionError(Exception):
    pass


def decrypt(ciphertext: str) -> str:
    key = _get_key()
    if not key:
        return ciphertext
    try:
        raw = base64.b64decode(ciphertext)
        nonce = raw[:12]
        ct = raw[12:]
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ct, None).decode('utf-8')
    except Exception as e:
        raise DecryptionError(f"Failed to decrypt value: {e}") from e
