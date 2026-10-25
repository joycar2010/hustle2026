"""Seed the QH-style one-persona-per-notification-template catalog."""

from alembic import op


revision = "e8f9a0b1c2d3"
down_revision = "d7e8f9a0b1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep stable ASCII keys so imports and subsequent deployments are
    # idempotent.  Chinese/localized labels remain an admin presentation concern.
    op.execute(
        """
        INSERT INTO sound_personas
          (skey, name, voice, style, rate_pct, pitch_pct, engine, lang, rate, pitch,
           voice_hint, edge_voice, edge_rate, edge_pitch, sample, sample_text, enabled, sort)
        VALUES
          ('tpl_singleleg', 'Single-leg alert persona', '', 'risk warning', -6, -10, 'edge', 'zh-CN', 1, 1, '', 'zh-CN-XiaoyiNeural', '-6%', '-10Hz', 'Single-leg exposure detected.', 'Warning. One leg filled and the hedge leg failed. Review it now.', TRUE, 11),
          ('tpl_naked', 'Unhedged exposure persona', '', 'critical risk warning', -10, -14, 'edge', 'zh-CN', 1, 1, '', 'zh-CN-XiaoyiNeural', '-10%', '-14Hz', 'Unhedged exposure detected.', 'Critical warning. Unhedged exposure is still open. Intervene now.', TRUE, 12),
          ('tpl_stoploss', 'Stop-loss persona', '', 'risk warning', -6, -10, 'edge', 'zh-CN', 1, 1, '', 'zh-CN-XiaoyiNeural', '-6%', '-10Hz', 'Stop-loss condition reached.', 'Stop-loss threshold reached. Confirm whether to close the position.', TRUE, 13),
          ('tpl_divergence', 'Spread divergence persona', '', 'risk warning', -6, -10, 'edge', 'zh-CN', 1, 1, '', 'zh-CN-XiaoyiNeural', '-6%', '-10Hz', 'Spread divergence guard triggered.', 'The spread divergence guard triggered. New entries are temporarily paused.', TRUE, 14),
          ('tpl_slippage', 'Slippage guard persona', '', 'risk warning', -6, -10, 'edge', 'zh-CN', 1, 1, '', 'zh-CN-XiaoyiNeural', '-6%', '-10Hz', 'Slippage protection triggered.', 'Slippage exceeded the configured tolerance. New orders are temporarily paused.', TRUE, 15),
          ('tpl_fluct', 'Volatility guard persona', '', 'risk warning', -6, -10, 'edge', 'zh-CN', 1, 1, '', 'zh-CN-XiaoyiNeural', '-6%', '-10Hz', 'Volatility guard triggered.', 'Market volatility exceeded the configured band. Entry is temporarily delayed.', TRUE, 16),
          ('tpl_margin', 'Margin reserve persona', '', 'critical risk warning', -8, -12, 'edge', 'zh-CN', 1, 1, '', 'zh-CN-XiaoyiNeural', '-8%', '-12Hz', 'Margin reserve is low.', 'Margin reserve is insufficient. The next entry was skipped.', TRUE, 17),
          ('tpl_marketclose', 'Market close persona', '', 'system reminder', 6, 10, 'edge', 'zh-CN', 1, 1, '', 'zh-CN-XiaoxiaoNeural', '+6%', '+10Hz', 'Market close reminder.', 'The market is approaching a scheduled close. Please review active positions.', TRUE, 21),
          ('tpl_announce', 'System announcement persona', '', 'system announcement', 8, 12, 'edge', 'zh-CN', 1, 1, '', 'zh-CN-XiaoxiaoNeural', '+8%', '+12Hz', 'System announcement.', 'There is a new system announcement. Please check it.', TRUE, 22),
          ('tpl_takeprofit', 'Take-profit persona', '', 'success notice', 10, 16, 'edge', 'zh-CN', 1, 1, '', 'zh-CN-XiaoxiaoNeural', '+10%', '+16Hz', 'Take-profit reached.', 'Congratulations. The take-profit target was reached.', TRUE, 23),
          ('tpl_entryspread', 'Entry spread persona', '', 'trading reminder', 6, 10, 'edge', 'zh-CN', 1, 1, '', 'zh-CN-XiaoxiaoNeural', '+6%', '+10Hz', 'Entry spread is high.', 'The entry spread is above the configured threshold. Waiting for a better opportunity.', TRUE, 24),
          ('tpl_weekendstop', 'Weekend stop persona', '', 'system reminder', 6, 10, 'edge', 'zh-CN', 1, 1, '', 'zh-CN-XiaoxiaoNeural', '+6%', '+10Hz', 'Weekend stop reminder.', 'Scheduled stop hours are active. Automated entry and exit are paused.', TRUE, 25),
          ('tpl_entitle', 'Entitlement downgrade persona', '', 'system reminder', 6, 10, 'edge', 'zh-CN', 1, 1, '', 'zh-CN-XiaoxiaoNeural', '+6%', '+10Hz', 'Entitlement downgrade.', 'The automatic trading entitlement is inactive and has switched to shadow mode.', TRUE, 26),
          ('tpl_ratelimit', 'API rate limit persona', '', 'system reminder', 6, 10, 'edge', 'zh-CN', 1, 1, '', 'zh-CN-XiaoxiaoNeural', '+6%', '+10Hz', 'API rate limit warning.', 'API usage is near its limit. Frequency has been reduced for protection.', TRUE, 27),
          ('tpl_capacity', 'Capacity reduction persona', '', 'trading reminder', 6, 10, 'edge', 'zh-CN', 1, 1, '', 'zh-CN-XiaoxiaoNeural', '+6%', '+10Hz', 'Capacity reduction.', 'Trading capacity was reduced and excess pending entry orders are being cancelled.', TRUE, 28)
        ON CONFLICT (skey) DO UPDATE SET
          name = EXCLUDED.name, style = EXCLUDED.style, engine = EXCLUDED.engine,
          lang = EXCLUDED.lang, edge_voice = EXCLUDED.edge_voice,
          edge_rate = EXCLUDED.edge_rate, edge_pitch = EXCLUDED.edge_pitch,
          sample_text = EXCLUDED.sample_text, enabled = TRUE, sort = EXCLUDED.sort
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM sound_personas WHERE skey LIKE 'tpl_%'"
    )
