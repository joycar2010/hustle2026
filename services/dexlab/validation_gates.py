#!/usr/bin/env python3
"""五道闸验证器 - PT-cUSD特化版本"""
import sqlite3
import json
from decimal import Decimal
from datetime import datetime
from pt_cusd_adapter import PTcUSDAdapter

class ValidationGates:
    """五道闸验证"""

    def __init__(self, db_path='dexlab.db'):
        self.db_path = db_path
        self.adapter = PTcUSDAdapter()

    def validate_g1_evidence(self, instrument_version: str) -> dict:
        """G1: 证据完整性"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        # 检查赎回模型是否存在
        cur.execute('''
            SELECT COUNT(*) FROM lab_redemption_models
            WHERE instrument_version = ? AND verification_status = 'VERIFIED'
        ''', (instrument_version,))
        has_model = cur.fetchone()[0] > 0

        # 检查证据（PT-cUSD需要的4项证据）
        required = ['CONTRACT_IDENTITY', 'EXCHANGE_RATE', 'REDEEM_STATUS', 'TARGET_QUOTE']
        cur.execute('''
            SELECT DISTINCT evidence_type FROM lab_evidence
            WHERE project_id = 'D2' AND evidence_type IN (?, ?, ?, ?)
        ''', tuple(required))
        present = [row[0] for row in cur.fetchall()]

        conn.close()

        missing = [r for r in required if r not in present]

        if not has_model:
            return {
                'gate_code': 'G1_EVIDENCE',
                'status': 'BLOCKED',
                'reason_codes': ['REDEMPTION_MODEL_MISSING'] + missing,
                'metrics': {'model_exists': False, 'evidence_coverage': len(present) / len(required)}
            }

        if missing:
            return {
                'gate_code': 'G1_EVIDENCE',
                'status': 'FAIL',
                'reason_codes': missing,
                'metrics': {'evidence_coverage': len(present) / len(required)}
            }

        return {
            'gate_code': 'G1_EVIDENCE',
            'status': 'PASS',
            'reason_codes': [],
            'metrics': {'evidence_coverage': 1.0, 'model_verified': True}
        }

    def validate_g2_economic(self, instrument_version: str, target_usd: Decimal, days_to_maturity: int, gross_bps: Decimal) -> dict:
        """G2: 经济可行性"""

        # 计算成本
        costs = self.adapter.calculate_full_cost(target_usd, days_to_maturity)
        total_cost_bps = Decimal(str(costs['total_cost_bps']))

        # 计算保守净收益
        conservative_net_bps = gross_bps - total_cost_bps

        # 安全边际阈值
        safety_margin = Decimal('10.0')  # 需要至少10bps

        if conservative_net_bps <= 0:
            return {
                'gate_code': 'G2_ECONOMIC',
                'status': 'FAIL',
                'reason_codes': ['CURRENT_COST_NEGATIVE'],
                'metrics': {
                    'gross_bps': float(gross_bps),
                    'cost_bps': float(total_cost_bps),
                    'net_bps': float(conservative_net_bps),
                    'cost_breakdown': costs['breakdown']
                }
            }

        if conservative_net_bps < safety_margin:
            return {
                'gate_code': 'G2_ECONOMIC',
                'status': 'FAIL',
                'reason_codes': ['INSUFFICIENT_SAFETY_MARGIN'],
                'metrics': {
                    'gross_bps': float(gross_bps),
                    'cost_bps': float(total_cost_bps),
                    'net_bps': float(conservative_net_bps),
                    'required_margin': float(safety_margin)
                }
            }

        return {
            'gate_code': 'G2_ECONOMIC',
            'status': 'PASS',
            'reason_codes': [],
            'metrics': {
                'gross_bps': float(gross_bps),
                'cost_bps': float(total_cost_bps),
                'net_bps': float(conservative_net_bps)
            }
        }

    def validate_all_gates(self, instrument_version: str, scenario: dict) -> dict:
        """运行所有闸门验证"""

        results = {}

        # G1: 证据
        results['G1'] = self.validate_g1_evidence(instrument_version)

        # G2: 经济
        results['G2'] = self.validate_g2_economic(
            instrument_version,
            Decimal(str(scenario['target_usd'])),
            scenario['days_to_maturity'],
            Decimal(str(scenario['gross_bps']))
        )

        # G3-G5: PT-cUSD不需要
        for gate in ['G3_STATISTICAL', 'G4_EXECUTION', 'G5_RISK']:
            results[gate] = {
                'gate_code': gate,
                'status': 'NOT_EVALUATED',
                'reason_codes': ['PT_CUSD_NOT_REQUIRED'],
                'metrics': {}
            }

        # 综合判决
        promotion_eligibility = 'RESEARCH_ONLY'
        blocking_reasons = []

        for gate_code, result in results.items():
            if result['status'] in ['FAIL', 'BLOCKED']:
                blocking_reasons.extend(result['reason_codes'])

        return {
            'gates': results,
            'promotion_eligibility': promotion_eligibility,
            'blocking_reasons': blocking_reasons
        }

    def save_gate_results(self, subject_id: str, results: dict) -> None:
        """保存闸门结果到数据库"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        timestamp = int(datetime.now().timestamp())

        for gate_code, result in results['gates'].items():
            cur.execute('''
                INSERT INTO lab_validation_gate_results
                (subject_type, subject_id, gate_code, status, policy_version,
                 reason_codes, metrics_json, evaluated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                'INSTRUMENT',
                subject_id,
                result['gate_code'],
                result['status'],
                'v1.0',
                json.dumps(result['reason_codes']),
                json.dumps(result['metrics']),
                timestamp
            ))

        conn.commit()
        conn.close()

if __name__ == '__main__':
    print('='*70)
    print('🚪 PT-cUSD五道闸验证测试')
    print('='*70)

    validator = ValidationGates()

    # 测试场景: PT-cUSD MAR2026
    scenario = {
        'target_usd': 10000,
        'days_to_maturity': 68,
        'gross_bps': 23.2  # 到期毛收益
    }

    print(f'\\n测试场景:')
    print(f'  目标金额: ${scenario["target_usd"]:,}')
    print(f'  距到期: {scenario["days_to_maturity"]}天')
    print(f'  毛收益: {scenario["gross_bps"]} bps')

    # 运行所有闸门
    results = validator.validate_all_gates('PT-cUSD-MAR2026', scenario)

    print(f'\\n五道闸结果:')
    for gate_code, result in results['gates'].items():
        status_icon = {'PASS': '✅', 'FAIL': '❌', 'BLOCKED': '🔴', 'NOT_EVALUATED': '⏸️'}
        icon = status_icon.get(result['status'], '❓')
        print(f'  {icon} {gate_code:20} {result["status"]}')
        if result['reason_codes']:
            for reason in result['reason_codes'][:2]:
                print(f'      - {reason}')

    print(f'\\n综合判决:')
    print(f'  晋级资格: {results["promotion_eligibility"]}')
    print(f'  阻断原因: {results["blocking_reasons"][:3]}')

    # 保存到数据库
    validator.save_gate_results('PT-cUSD-MAR2026', results)
    print(f'\\n✓ 闸门结果已保存到数据库')

    print('='*70)
