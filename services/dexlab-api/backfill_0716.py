# 一次性回填(2026-07-16):D1 空壳报告正文 + D3 判决验尸报告证据。幂等可重跑。
import sqlite3
import time

c = sqlite3.connect("/home/ec2-user/dexlab/dexlab.db")
now = int(time.time())

D1_SUMMARY = (
    "可赎回稳定币/LST/ERC-4626 折价｜链/协议:ETH L1/L2｜当前阶段:IDEA\n"
    "尚无测量/回放/影子轮次——项目处于想法阶段,报告仅登记现状\n"
    "证据条目:0 条\n尚无判决\n"
    "下一步:定义标的池(可赎回稳定币/LST/4626金库)+折价扫描器,进入 MEASURE"
)
c.execute("UPDATE research_outbox SET summary=? WHERE project_id='D1' "
          "AND (summary='' OR summary IS NULL)", (D1_SUMMARY,))

D3_BODY = (
    "结论:DEX买入-CEX对冲-充值卖出 全向证伪,项目 KILL。\n"
    "① 成本线:全链路往返成本约 38bps(DEX swap+gas+CEX taker+充提)——专业玩家把可见价差"
    "长期钉在其成本线以内,扫描到的『超额价差』几乎全部位于我们的成本线之外、别人的成本线之内;\n"
    "② 假阳性来源一:死池污染——低流动性池的陈旧报价被扫描器当成可成交价,把价差中位数系统性抬高;\n"
    "③ 假阳性来源二:锚定币折价——LST/包装资产的『折价』实为赎回期限与信用风险定价,不是套利空间;\n"
    "④ 真金 canary:P1 阶段修复 11 个真金 bug 后全链路可跑,但净期望仍为负;\n"
    "⑤ 出路判断:与其跨域套利,不如刷 CEX 量降 VIP 费率(转 O1/做量方向)。\n"
    "详情:CrossArb P0/P1 工具链保留在 crossarb 仓库,可复扫验证。"
)
c.execute("INSERT INTO lab_evidence(project_id,run_id,kind,title,body,created_at) "
          "SELECT 'D3',NULL,'verdict_report','CrossArb 五方向证伪·验尸报告(摘要)',?,? "
          "WHERE NOT EXISTS(SELECT 1 FROM lab_evidence WHERE project_id='D3' "
          "AND kind='verdict_report')", (D3_BODY, now))
c.commit()
print("outbox:", list(c.execute("SELECT project_id, length(summary) FROM research_outbox")))
print("evidence:", list(c.execute("SELECT project_id, kind, title FROM lab_evidence")))
