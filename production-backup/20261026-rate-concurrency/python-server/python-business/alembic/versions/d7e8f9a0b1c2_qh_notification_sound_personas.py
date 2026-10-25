"""Expand notification sound personas and align QH notification defaults.

The migration is additive.  Existing tone keys and the legacy browser-TTS
columns remain valid, while configurable Edge/browser personas become the
canonical source for template and marquee voice selection.
"""

from alembic import op


revision = "d7e8f9a0b1c2"
down_revision = "c6d7e8f9a0b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in (
        "ALTER TABLE sound_personas ADD COLUMN IF NOT EXISTS engine VARCHAR(20) NOT NULL DEFAULT 'browser'",
        "ALTER TABLE sound_personas ADD COLUMN IF NOT EXISTS lang VARCHAR(20) NOT NULL DEFAULT 'zh-CN'",
        "ALTER TABLE sound_personas ADD COLUMN IF NOT EXISTS rate DOUBLE PRECISION NOT NULL DEFAULT 1.0",
        "ALTER TABLE sound_personas ADD COLUMN IF NOT EXISTS pitch DOUBLE PRECISION NOT NULL DEFAULT 1.0",
        "ALTER TABLE sound_personas ADD COLUMN IF NOT EXISTS voice_hint VARCHAR(200) NOT NULL DEFAULT ''",
        "ALTER TABLE sound_personas ADD COLUMN IF NOT EXISTS edge_voice VARCHAR(160) NOT NULL DEFAULT 'zh-CN-XiaoxiaoNeural'",
        "ALTER TABLE sound_personas ADD COLUMN IF NOT EXISTS edge_rate VARCHAR(20) NOT NULL DEFAULT '+0%'",
        "ALTER TABLE sound_personas ADD COLUMN IF NOT EXISTS edge_pitch VARCHAR(20) NOT NULL DEFAULT '+0Hz'",
        "ALTER TABLE sound_personas ADD COLUMN IF NOT EXISTS sample_text VARCHAR(500) NOT NULL DEFAULT 'This is a notification voice preview.'",
        "ALTER TABLE sound_personas ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE sound_personas ADD COLUMN IF NOT EXISTS sort INTEGER NOT NULL DEFAULT 0",
    ):
        op.execute(statement)

    # Upgrade the existing QH-compatible generic personas in place.
    op.execute(
        """
        UPDATE sound_personas
        SET engine='edge', lang='zh-CN', rate=1.0, pitch=1.0,
            edge_voice=CASE WHEN skey IN ('royal', 'mature')
                            THEN 'zh-CN-XiaoyiNeural'
                            ELSE 'zh-CN-XiaoxiaoNeural' END,
            edge_rate=CASE WHEN skey IN ('royal', 'mature') THEN '-5%' ELSE '+6%' END,
            edge_pitch=CASE WHEN skey IN ('royal', 'mature') THEN '-8Hz' ELSE '+10Hz' END,
            sample_text=CASE WHEN skey IN ('royal', 'mature')
                             THEN 'Risk warning. Please review the account immediately.'
                             ELSE 'A new notification is ready. Please check it.' END,
            enabled=TRUE
        WHERE skey IN ('sweet', 'royal', 'calm', 'urgent', 'mature')
        """
    )

    # Dedicated event voices mirror QH p26.  They are intentionally seeded
    # with stable ASCII keys so old installations can safely re-run deploys.
    op.execute(
        """
        INSERT INTO sound_personas
          (skey, name, voice, style, rate_pct, pitch_pct, engine, lang, rate, pitch,
           voice_hint, edge_voice, edge_rate, edge_pitch, sample, sample_text, enabled, sort)
        VALUES
          ('risk_single_leg', 'Single-leg warning', '', 'serious risk warning',  -6, -10, 'edge', 'zh-CN', 1, 1, '', 'zh-CN-XiaoyiNeural', '-6%',  '-10Hz', 'Single-leg exposure detected.', 'Warning. One leg filled and the hedge leg failed. Review it now.', TRUE, 11),
          ('risk_naked',      'Unhedged exposure',  '', 'critical risk warning', -10, -14, 'edge', 'zh-CN', 1, 1, '', 'zh-CN-XiaoyiNeural', '-10%', '-14Hz', 'Unhedged exposure detected.', 'Critical warning. Unhedged exposure is still open. Intervene now.', TRUE, 12),
          ('risk_stop_loss',  'Stop-loss advice',   '', 'serious risk warning',  -6, -10, 'edge', 'zh-CN', 1, 1, '', 'zh-CN-XiaoyiNeural', '-6%',  '-10Hz', 'Stop-loss condition reached.', 'Stop-loss threshold reached. Confirm whether to close the position.', TRUE, 13),
          ('risk_margin',     'Margin reserve',     '', 'critical risk warning',  -8, -12, 'edge', 'zh-CN', 1, 1, '', 'zh-CN-XiaoyiNeural', '-8%',  '-12Hz', 'Margin reserve is low.', 'Margin reserve is insufficient. The next entry was skipped.', TRUE, 17),
          ('trade_market',    'Market reminder',   '', 'friendly trading notice',  6,  10, 'edge', 'zh-CN', 1, 1, '', 'zh-CN-XiaoxiaoNeural', '+6%',  '+10Hz', 'Market reminder.', 'A market notification is ready. Please check it when convenient.', TRUE, 21),
          ('trade_announce',  'System announcement','', 'friendly system notice',  8,  12, 'edge', 'zh-CN', 1, 1, '', 'zh-CN-XiaoxiaoNeural', '+8%',  '+12Hz', 'System announcement.', 'There is a new system announcement. Please check it.', TRUE, 22),
          ('trade_take_profit','Take-profit notice','', 'friendly success notice', 10, 16, 'edge', 'zh-CN', 1, 1, '', 'zh-CN-XiaoxiaoNeural', '+10%', '+16Hz', 'Take-profit reached.', 'Congratulations. The take-profit target was reached.', TRUE, 23),
          ('early_borrow',    'Early borrow advice','', 'calm market suggestion',   4,   6, 'edge', 'zh-CN', 1, 1, '', 'zh-CN-XiaoxiaoNeural', '+4%',  '+6Hz', 'Early borrow suggestion.', 'This is only a borrow-readiness suggestion. No automatic borrowing or order is performed.', TRUE, 30)
        ON CONFLICT (skey) DO UPDATE SET
          name=EXCLUDED.name, style=EXCLUDED.style, engine=EXCLUDED.engine,
          lang=EXCLUDED.lang, edge_voice=EXCLUDED.edge_voice,
          edge_rate=EXCLUDED.edge_rate, edge_pitch=EXCLUDED.edge_pitch,
          sample_text=EXCLUDED.sample_text, enabled=TRUE, sort=EXCLUDED.sort
        """
    )

    # Existing Coin templates used tone keys.  Only migrate those known keys;
    # custom administrator mappings are left untouched.
    op.execute(
        """
        UPDATE notification_templates
        SET sound_key = CASE
          WHEN category = 'risk' THEN 'royal'
          WHEN template_name = 'early_borrow_advice' THEN 'early_borrow'
          ELSE 'sweet'
        END
        WHERE sound_key IN ('ding', 'success', 'alert', 'error', 'chime', 'early_borrow')
        """
    )


def downgrade() -> None:
    # Keep the migration reversible for schema tooling.  Do not remove the
    # legacy columns because older deployments may still read them.
    for column in (
        "sort", "enabled", "sample_text", "edge_pitch", "edge_rate",
        "edge_voice", "voice_hint", "pitch", "rate", "lang", "engine",
    ):
        op.execute(f"ALTER TABLE sound_personas DROP COLUMN IF EXISTS {column}")
