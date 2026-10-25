"""Add QH-compatible site notices, maintenance state, and sound personas.

The notification center is deliberately independent from the trading worker.  A
maintenance update only records an operator-visible state and can be consumed by
the public site; it must not start/stop a worker or call an exchange API.

Revision ID: ab88cc99dd00
Revises: aa77bb88cc99
"""

from alembic import op


revision = "ab88cc99dd00"
down_revision = "aa77bb88cc99"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS keeps this migration safe for installations that were
    # bootstrapped with SQLAlchemy metadata before Alembic was enabled.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS site_notices (
            id SERIAL PRIMARY KEY,
            kind VARCHAR(20) NOT NULL DEFAULT 'notice',
            title VARCHAR(200) NOT NULL DEFAULT '',
            content TEXT NOT NULL DEFAULT '',
            enabled BOOLEAN NOT NULL DEFAULT FALSE,
            starts_at TIMESTAMPTZ NULL,
            ends_at TIMESTAMPTZ NULL,
            updated_by VARCHAR(100) NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_site_notices_kind ON site_notices (kind)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_site_notices_enabled ON site_notices (enabled)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS notification_maintenance (
            id INTEGER PRIMARY KEY,
            enabled BOOLEAN NOT NULL DEFAULT FALSE,
            stop_strategy BOOLEAN NOT NULL DEFAULT TRUE,
            block_trading BOOLEAN NOT NULL DEFAULT TRUE,
            block_login BOOLEAN NOT NULL DEFAULT FALSE,
            title VARCHAR(200) NOT NULL DEFAULT '系统维护中',
            content TEXT NOT NULL DEFAULT '',
            until_at TIMESTAMPTZ NULL,
            updated_by VARCHAR(100) NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        INSERT INTO notification_maintenance (id)
        VALUES (1)
        ON CONFLICT (id) DO NOTHING
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sound_personas (
            id SERIAL PRIMARY KEY,
            skey VARCHAR(40) NOT NULL UNIQUE,
            name VARCHAR(80) NOT NULL,
            voice VARCHAR(160) NOT NULL DEFAULT '',
            style VARCHAR(200) NOT NULL DEFAULT '',
            rate_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
            pitch_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
            sample VARCHAR(500) NOT NULL DEFAULT '',
            updated_by VARCHAR(100) NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        INSERT INTO sound_personas(skey, name, voice, style, rate_pct, pitch_pct, sample)
        VALUES
            ('sweet', '甜妹', 'zh-CN-XiaoxiaoNeural', '甜美/元气', 0, 0, '亲，这是一条通知试听。'),
            ('royal', '御姐', 'zh-CN-XiaoyiNeural', '沉稳/高注意力', -5, -2, '请注意风险告警。'),
            ('calm', '平稳', '', 'neutral, steady', 0, 0, 'System notification preview'),
            ('urgent', '紧急', '', 'short, clear, high attention', 8, 12, 'Risk alert preview')
        ON CONFLICT (skey) DO NOTHING
        """
    )
    # Stable key used by read-only early-borrow analytics.  Keep this seed
    # idempotent so existing custom templates are never overwritten.
    op.execute(
        """
        INSERT INTO notification_templates
            (template_name, category, title_template, content_template,
             enable_feishu, enable_email, enable_marquee, priority,
             cooldown_seconds, marquee_color, marquee_blink, sound_key, is_enabled)
        SELECT
            'early_borrow_advice', 'market', 'Early borrow suggestion',
            'Symbol {symbol} matches a historical spread case ({similarity}%); review borrow readiness. No automatic borrowing or order is performed.',
            TRUE, FALSE, TRUE, 2, 300, '#f59e0b', FALSE, 'chime', TRUE
        WHERE NOT EXISTS (
            SELECT 1 FROM notification_templates WHERE template_name = 'early_borrow_advice'
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sound_personas")
    op.execute("DROP TABLE IF EXISTS notification_maintenance")
    op.execute("DROP INDEX IF EXISTS ix_site_notices_enabled")
    op.execute("DROP INDEX IF EXISTS ix_site_notices_kind")
    op.execute("DROP TABLE IF EXISTS site_notices")
