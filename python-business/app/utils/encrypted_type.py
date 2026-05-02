from sqlalchemy import String, TypeDecorator

from app.utils.crypto import encrypt, decrypt


class EncryptedString(TypeDecorator):
    impl = String
    cache_ok = True

    def __init__(self, length=None):
        super().__init__(length=length)

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        return encrypt(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        return decrypt(value)
