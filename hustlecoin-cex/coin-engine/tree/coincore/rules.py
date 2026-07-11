"""规则清理:原 app.api.engine_api._purge_symbol_rules 搬入——
修复 engine→app.api 的倒挂依赖(引擎不得依赖 API 层),API 层反向引用本处。"""
from sqlalchemy.orm import Session


def purge_symbol_rules(db: Session, user_id: int, symbol: str, sub_account_ids: list = None):
    """清除某币的单一规则(SymbolRule + AccountSymbolRule),使再推进来时回归全局默认。
    供 HTTP DELETE 手动移除 & 引擎平仓后自动下架 两条路径复用。"""
    from coincore.models import SymbolRule, AccountSymbolRule
    try:
        db.query(SymbolRule).filter(
            SymbolRule.user_id == user_id, SymbolRule.symbol == symbol,
        ).delete(synchronize_session=False)
        if sub_account_ids:
            db.query(AccountSymbolRule).filter(
                AccountSymbolRule.sub_account_id.in_(sub_account_ids),
                AccountSymbolRule.symbol == symbol,
            ).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()


_purge_symbol_rules = purge_symbol_rules  # 兼容旧名
