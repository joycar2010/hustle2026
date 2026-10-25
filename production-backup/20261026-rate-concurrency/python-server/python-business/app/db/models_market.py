# PendingBlacklist 已统一到 app.db.models(规范定义,含全部列)。
# 此处仅做兼容性再导出,避免重复定义同一张表(双注册会触发 SQLAlchemy "Table already defined")。
from app.db.models import PendingBlacklist  # noqa: F401
