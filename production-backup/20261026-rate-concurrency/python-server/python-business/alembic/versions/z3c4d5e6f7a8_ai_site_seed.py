"""Seed isolated AI configs and starter knowledge for both sites."""

from alembic import op
import sqlalchemy as sa


revision = "z3c4d5e6f7a8"
down_revision = "z2b3c4d5e6f7"
branch_labels = None
depends_on = None


_FAQS = (
    ("借币与还币", "系统只会在规则、库存和行情均满足条件时借币；平仓后先完成对冲、买回和还债，再处理已证明的残留。"),
    ("行情未到", "现货和合约行情必须同时处于新鲜窗口；任一来源缺失或过期时不会触发开仓或平仓。"),
    ("残留清理", "自动清理仅处理无活动仓位、无债务且能由已完成买回记录证明归属的残留，不会清理正常仓位。"),
    ("参数来源", "单一规则优先于通用规则；未配置单一规则时才使用币种通用规则。"),
)


def upgrade() -> None:
    bind = op.get_bind()
    for site in ("coin", "coinadmin"):
        # Create a separate config row for every site.  Copy provider/model
        # values from the legacy default row when available, but never copy a
        # credential into a response; the API masks it separately.
        bind.execute(sa.text(
            "INSERT INTO ai_config (site, provider, api_key, base_url, model_name, temperature, max_tokens, system_prompt, is_enabled, rate_limit_per_min) "
            "SELECT :site, provider, api_key, base_url, model_name, temperature, max_tokens, system_prompt, is_enabled, rate_limit_per_min "
            "FROM ai_config src WHERE src.site = 'default' "
            "AND NOT EXISTS (SELECT 1 FROM ai_config dst WHERE dst.site = :site)"
        ).bindparams(site=site))
        bind.execute(sa.text(
            "INSERT INTO ai_config (site, provider, model_name, temperature, max_tokens, system_prompt, is_enabled, rate_limit_per_min) "
            "SELECT :site, 'claude', 'claude-sonnet-4-6', 0.7, 2000, '', false, 10 "
            "WHERE NOT EXISTS (SELECT 1 FROM ai_config dst WHERE dst.site = :site)"
        ).bindparams(site=site))
        for idx, (category, answer) in enumerate(_FAQS):
            question = f"{category}常见问题"
            bind.execute(sa.text(
                "INSERT INTO ai_faq (site, question, answer, category, sort_order, is_active) "
                "SELECT :site, :question, :answer, :category, :sort_order, true "
                "WHERE NOT EXISTS (SELECT 1 FROM ai_faq WHERE site = :site AND question = :question)"
            ).bindparams(site=site, question=question, answer=answer,
                         category=category, sort_order=idx))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM ai_faq WHERE site IN ('coin', 'coinadmin') AND question LIKE '%常见问题'"))
    bind.execute(sa.text("DELETE FROM ai_config WHERE site IN ('coin', 'coinadmin')"))
