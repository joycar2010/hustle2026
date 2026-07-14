-- 0016: G1 策略 fencing 升级(V5 补充说明 ADR-005)——(policy_epoch, sequence) 双单调。
-- G0 只有 policy_version(sequence);G1 加 policy_epoch:DB 恢复/主从切换/权威重建后须 bump epoch,
-- 避免 sequence 回退使旧快照复活(消费者按 (epoch, sequence) 字典序只接受更高)。
ALTER TABLE risk_policy_version ADD COLUMN IF NOT EXISTS policy_epoch BIGINT NOT NULL DEFAULT 1;
