-- 0024: manager:config PG 持久化(保护性收尾 0722)。
-- 闭合 sole-authority 盲区:exec-manager 的 watch-list/config 此前只活在 Redis
-- 单键 dcm:exec:manager:config,Redis 被 wipe(混沌演练 FLUSHALL)即彻底丢失,
-- manager 重启后 expected 全空→在管仓失管、recon 扫不到→只剩 R11 兜底。
-- 本表为该 config 的 write-through 单行快照:
--   * manager 每轮读 Redis 权威键,非空则镜像到本表(仅 hash 变化时写);
--   * Redis 键"缺失"(GET=None,疑重置)且本表快照非空 + exec_saga 有 OPEN 行
--     (真有仓要管)→ 自愈恢复 watch-list 并告警 config-selfheal;
--   * Redis 键"存在但空"(操作员主动清空)→ 尊重不复活,空值照常镜像。
-- 单行表(id 恒为 1),非事件日志。
CREATE TABLE IF NOT EXISTS exec_manager_config (
    id         INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    config     JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mix_ro') THEN
        GRANT SELECT ON exec_manager_config TO mix_ro;
    END IF;
END $$;
