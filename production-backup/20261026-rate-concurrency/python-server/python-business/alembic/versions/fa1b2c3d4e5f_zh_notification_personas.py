"""Normalize notification voices and preview copy to Chinese female speech.

Older QH seed rows used English names and sample text even though the Edge
voice was later changed to a Chinese voice.  That made the audible fallback
sound inconsistent.  This migration is idempotent and only touches the
notification persona catalog; it does not change delivery or trading policy.
"""

from alembic import op


revision = "fa1b2c3d4e5f"
down_revision = "a0b1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep risk events on the direct, lower-pitched female voice and all other
    # events on the warmer female voice.  Explicitly constrain the locale so
    # an old en-US row cannot be selected by the browser fallback.
    op.execute(
        """
        UPDATE sound_personas
        SET lang = 'zh-CN',
            engine = 'edge',
            edge_voice = CASE
                WHEN skey IN (
                    'royal', 'urgent', 'mature', 'risk_single_leg', 'risk_naked',
                    'risk_stop_loss', 'risk_margin', 'tpl_singleleg', 'tpl_naked',
                    'tpl_stoploss', 'tpl_divergence', 'tpl_slippage', 'tpl_fluct',
                    'tpl_margin'
                ) OR lower(coalesce(style, '')) LIKE '%risk%'
                  OR lower(coalesce(style, '')) LIKE '%warning%'
                  OR lower(coalesce(style, '')) LIKE '%alert%'
                THEN 'zh-CN-XiaoyiNeural'
                ELSE 'zh-CN-XiaoxiaoNeural'
            END,
            voice = CASE
                WHEN skey IN (
                    'royal', 'urgent', 'mature', 'risk_single_leg', 'risk_naked',
                    'risk_stop_loss', 'risk_margin', 'tpl_singleleg', 'tpl_naked',
                    'tpl_stoploss', 'tpl_divergence', 'tpl_slippage', 'tpl_fluct',
                    'tpl_margin'
                ) OR lower(coalesce(style, '')) LIKE '%risk%'
                  OR lower(coalesce(style, '')) LIKE '%warning%'
                  OR lower(coalesce(style, '')) LIKE '%alert%'
                THEN 'zh-CN-XiaoyiNeural'
                ELSE 'zh-CN-XiaoxiaoNeural'
            END,
            voice_hint = CASE
                WHEN skey IN (
                    'royal', 'urgent', 'mature', 'risk_single_leg', 'risk_naked',
                    'risk_stop_loss', 'risk_margin', 'tpl_singleleg', 'tpl_naked',
                    'tpl_stoploss', 'tpl_divergence', 'tpl_slippage', 'tpl_fluct',
                    'tpl_margin'
                ) OR lower(coalesce(style, '')) LIKE '%risk%'
                  OR lower(coalesce(style, '')) LIKE '%warning%'
                  OR lower(coalesce(style, '')) LIKE '%alert%'
                THEN 'zh-CN-XiaoyiNeural'
                ELSE 'zh-CN-XiaoxiaoNeural'
            END
        """
    )

    # Localize the built-in catalog.  Custom rows with Chinese copy are left
    # intact; legacy all-ASCII seed copy gets a neutral Chinese fallback.
    op.execute(
        """
        UPDATE sound_personas
        SET name = CASE skey
            WHEN 'sweet' THEN '甜妹'
            WHEN 'royal' THEN '御姐'
            WHEN 'calm' THEN '平稳'
            WHEN 'urgent' THEN '紧急御姐'
            WHEN 'risk_single_leg' THEN '单腿风险'
            WHEN 'risk_naked' THEN '裸空风险'
            WHEN 'risk_stop_loss' THEN '止损预警'
            WHEN 'risk_margin' THEN '保证金风险'
            WHEN 'trade_market' THEN '行情提醒'
            WHEN 'trade_announce' THEN '系统公告'
            WHEN 'trade_take_profit' THEN '止盈提醒'
            WHEN 'early_borrow' THEN '提前借币建议'
            ELSE CASE WHEN name ~ '[一-龥]' THEN name ELSE '交易提醒' END
        END,
        style = CASE
            WHEN skey IN ('royal', 'urgent', 'mature', 'risk_single_leg', 'risk_naked',
                          'risk_stop_loss', 'risk_margin', 'tpl_singleleg', 'tpl_naked',
                          'tpl_stoploss', 'tpl_divergence', 'tpl_slippage', 'tpl_fluct',
                          'tpl_margin') THEN '严肃/风险告警'
            ELSE CASE WHEN style ~ '[一-龥]' THEN style ELSE '友好/交易通知' END
        END,
        sample = CASE
            WHEN skey = 'sweet' THEN '亲，这是一条通知试听。'
            WHEN skey = 'royal' THEN '请注意风险告警。'
            WHEN skey = 'calm' THEN '这是一条平稳的系统通知。'
            WHEN skey = 'urgent' THEN '请立即检查风险告警。'
            WHEN skey = 'early_borrow' THEN '这是提前借币建议，不会自动借币或下单。'
            WHEN skey IN ('risk_single_leg', 'tpl_singleleg') THEN '检测到单腿成交，请立即检查对冲状态。'
            WHEN skey IN ('risk_naked', 'tpl_naked') THEN '检测到未对冲仓位，请立即处理。'
            WHEN skey IN ('risk_stop_loss', 'tpl_stoploss') THEN '已达到止损条件，请确认是否平仓。'
            WHEN skey IN ('risk_margin', 'tpl_margin') THEN '保证金储备不足，系统已跳过下一次开仓。'
            WHEN sample ~ '[一-龥]' THEN sample
            ELSE '有新的交易通知，请及时查看。'
        END,
        sample_text = CASE
            WHEN skey = 'sweet' THEN '亲，这是一条通知试听。'
            WHEN skey = 'royal' THEN '请注意风险告警。'
            WHEN skey = 'calm' THEN '这是一条平稳的系统通知。'
            WHEN skey = 'urgent' THEN '请立即检查风险告警。'
            WHEN skey = 'early_borrow' THEN '这是提前借币建议，不会自动借币或下单。'
            WHEN skey IN ('risk_single_leg', 'tpl_singleleg') THEN '检测到单腿成交，请立即检查对冲状态。'
            WHEN skey IN ('risk_naked', 'tpl_naked') THEN '检测到未对冲仓位，请立即处理。'
            WHEN skey IN ('risk_stop_loss', 'tpl_stoploss') THEN '已达到止损条件，请确认是否平仓。'
            WHEN skey IN ('risk_margin', 'tpl_margin') THEN '保证金储备不足，系统已跳过下一次开仓。'
            WHEN sample_text ~ '[一-龥]' THEN sample_text
            ELSE '有新的交易通知，请及时查看。'
        END
        """
    )


def downgrade() -> None:
    # Deliberately leave localized data in place.  Reverting a deployment must
    # not reintroduce an English voice into an active notification channel.
    pass
