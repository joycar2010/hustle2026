-- AI 智能体接入开关 + 运维助手回答范围(单行权威;发布进 dcm:llm:config.agents 热生效)
-- 部署: sudo -u postgres psql -d mix_main -f 0002_llm_agents.sql
CREATE TABLE IF NOT EXISTS llm_agent_settings (
    id               SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    advisor_enabled  BOOLEAN NOT NULL DEFAULT TRUE,   -- LLM 评审顾问(llm-advisor,15min 组合评审)
    ops_chat_enabled BOOLEAN NOT NULL DEFAULT TRUE,   -- 运维助手(右下 AI 浮框对话)
    chat_scope       TEXT NOT NULL DEFAULT 'site' CHECK (chat_scope IN ('site', 'open')),
    updated_by       TEXT NOT NULL DEFAULT '',
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO llm_agent_settings(id) VALUES (1) ON CONFLICT DO NOTHING;
GRANT SELECT, INSERT, UPDATE ON llm_agent_settings TO mix_app;
