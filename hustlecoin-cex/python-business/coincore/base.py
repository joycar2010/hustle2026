"""模型基类真身(分家二期 M2 箭头翻转):Base 从 app.db.models 迁此。
app.db.models 与 engine.models 双侧从这里取——模型层单一真身,互相登记的三角消失。
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
