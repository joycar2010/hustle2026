#!/usr/bin/env python3
"""
D1多标的Episode聚合器
适配D1的多标的信号格式
"""
import sqlite3
import json
from decimal import Decimal
from typing import List, Dict
from datetime import datetime

class D1MultiAssetAggregator:
    """D1多标的Episode聚合器"""

    def __init__(self, db_path='dexlab.db'):
        self.db_path = db_path
        # 降低阈值以匹配D1实际数据
        self.entry_threshold_bps = Decimal('5.0')
        self.exit_threshold_bps = Decimal('0.0')
        self.entry_consecutive = 2
        self.exit_consecutive = 2

    def aggregate_d1_episodes(self, run_id: int) -> Dict:
        """聚合D1的多标的Episode"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        # 获取D1所有信号
        cur.execute('''
            SELECT id, ts, payload
            FROM lab_signal
            WHERE project_id = 'D1'
            ORDER BY ts
        ''')

        signals = cur.fetchall()
        conn.close()

        # 按标的分组处理
        assets_data = {}

        for sig_id, ts, payload_str in signals:
            payload = json.loads(payload_str)

            # 提取每个标的的信号
            for asset_sig in payload.get('signals', []):
                asset = asset_sig['asset']
                discount_bps = Decimal(str(asset_sig.get('discount_bps', 0)))

                if asset not in assets_data:
                    assets_data[asset] = []

                assets_data[asset].append({
                    'ts': ts,
                    'sig_id': sig_id,
                    'discount_bps': discount_bps,
                    'kind': asset_sig.get('kind', '')
                })

        # 为每个标的聚合Episode
        all_episodes = []
        for asset, data_points in assets_data.items():
            episodes = self._aggregate_asset_episodes(
                run_id, asset, data_points
            )
            all_episodes.extend(episodes)

        return {
            'total_episodes': len(all_episodes),
            'episodes_by_asset': {
                asset: len([e for e in all_episodes if asset in e['route_key']])
                for asset in assets_data.keys()
            },
            'episodes': all_episodes,
            'assets_tracked': list(assets_data.keys()),
            'total_signals': len(signals),
            'signal_count_by_asset': {
                asset: len(data_points)
                for asset, data_points in assets_data.items()
            }
        }

    def _aggregate_asset_episodes(
        self,
        run_id: int,
        asset: str,
        data_points: List[Dict]
    ) -> List[Dict]:
        """为单个标的聚合Episode"""

        episodes = []
        current_ep = None
        entry_count = 0
        exit_count = 0

        for i, point in enumerate(data_points):
            discount = point['discount_bps']

            # 折价为正值才是买入机会
            if discount > self.entry_threshold_bps:
                entry_count += 1
                exit_count = 0

                if entry_count >= self.entry_consecutive and not current_ep:
                    current_ep = {
                        'episode_id': f'EP-D1-{run_id}-{asset}-{len(episodes)+1}',
                        'run_id': run_id,
                        'instrument_version': f'D1-{asset}',
                        'route_key': f'redeem-{asset}',
                        'started_at': point['ts'],
                        'entry_sig_id': point['sig_id'],
                        'observations': [discount]
                    }

            elif discount <= self.exit_threshold_bps:
                exit_count += 1
                entry_count = 0

                if current_ep:
                    current_ep['observations'].append(discount)

                    if exit_count >= self.exit_consecutive:
                        # 关闭Episode
                        current_ep['ended_at'] = point['ts']
                        current_ep['exit_sig_id'] = point['sig_id']
                        current_ep['duration'] = current_ep['ended_at'] - current_ep['started_at']
                        current_ep['observation_count'] = len(current_ep['observations'])

                        # 统计
                        obs = current_ep['observations']
                        current_ep['gross_edge_bps'] = float(sum(obs) / len(obs))
                        current_ep['mae_bps'] = float(min(obs))
                        current_ep['mfe_bps'] = float(max(obs))
                        current_ep['entry_feasible'] = 1
                        current_ep['exit_feasible'] = 1

                        del current_ep['observations']
                        episodes.append(current_ep)
                        current_ep = None

            else:
                entry_count = 0
                exit_count = 0
                if current_ep:
                    current_ep['observations'].append(discount)

        # 关闭未结束的Episode
        if current_ep:
            current_ep['ended_at'] = data_points[-1]['ts']
            current_ep['duration'] = current_ep['ended_at'] - current_ep['started_at']
            current_ep['observation_count'] = len(current_ep['observations'])
            obs = current_ep['observations']
            current_ep['gross_edge_bps'] = float(sum(obs) / len(obs))
            current_ep['mae_bps'] = float(min(obs))
            current_ep['mfe_bps'] = float(max(obs))
            current_ep['false_positive_reason'] = 'RIGHT_CENSORED'
            del current_ep['observations']
            episodes.append(current_ep)

        return episodes

    def save_episodes(self, episodes: List[Dict]) -> int:
        """保存Episode到数据库"""
        conn = sqlite3.connect(self.db_path)
        conn.execute('PRAGMA busy_timeout = 30000')
        cur = conn.cursor()

        saved = 0
        for ep in episodes:
            cur.execute('''
                INSERT INTO lab_episodes
                (episode_id, run_id, instrument_version, route_key,
                 started_at, ended_at, duration, observation_count,
                 entry_quote_ids, exit_quote_ids,
                 gross_edge_bps, mae_bps, mfe_bps,
                 entry_feasible, exit_feasible, false_positive_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                ep['episode_id'],
                ep['run_id'],
                ep['instrument_version'],
                ep['route_key'],
                ep['started_at'],
                ep['ended_at'],
                ep['duration'],
                ep['observation_count'],
                json.dumps([ep.get('entry_sig_id')]),
                json.dumps([ep.get('exit_sig_id')]),
                ep['gross_edge_bps'],
                ep['mae_bps'],
                ep['mfe_bps'],
                ep.get('entry_feasible', 0),
                ep.get('exit_feasible', 0),
                ep.get('false_positive_reason')
            ))
            saved += 1

        conn.commit()
        conn.close()
        return saved

    def generate_coverage_report(self, result: Dict) -> Dict:
        """生成覆盖率报告"""

        # D1运行时间跨度（假设30天，5分钟间隔）
        expected_slots = 30 * 24 * 12  # 8640个5分钟槽
        observed_signals = result['total_signals']
        coverage_ratio = observed_signals / expected_slots

        return {
            'expected_slots': expected_slots,
            'observed_signals': observed_signals,
            'coverage_ratio': coverage_ratio,
            'coverage_pct': coverage_ratio * 100,
            'missing_slots': expected_slots - observed_signals,
            'episodes_identified': result['total_episodes'],
            'episodes_per_asset': result['episodes_by_asset'],
            'signal_concentration': result['signal_count_by_asset']
        }

if __name__ == '__main__':
    print('='*70)
    print('📦 D1多标的Episode聚合')
    print('='*70)

    aggregator = D1MultiAssetAggregator()

    # 聚合
    print('\n执行聚合...')
    result = aggregator.aggregate_d1_episodes(run_id=4)

    print(f'\n✓ 识别出 {result["total_episodes"]} 个Episode')
    print(f'  跟踪标的: {len(result["assets_tracked"])} 个')
    print(f'  总信号数: {result["total_signals"]}')

    print(f'\n按标的分布:')
    for asset, count in result['episodes_by_asset'].items():
        sig_count = result['signal_count_by_asset'][asset]
        print(f'  {asset:10} {count:3} episodes ({sig_count} signals)')

    # 覆盖率
    print(f'\n覆盖率分析:')
    coverage = aggregator.generate_coverage_report(result)
    print(f'  期望时间槽: {coverage["expected_slots"]:,}')
    print(f'  观测信号数: {coverage["observed_signals"]}')
    print(f'  覆盖率: {coverage["coverage_pct"]:.2f}%')
    print(f'  缺失槽: {coverage["missing_slots"]:,}')

    # 保存
    if result['episodes']:
        print(f'\n保存到数据库...')
        saved = aggregator.save_episodes(result['episodes'])
        print(f'✓ 已保存 {saved} 个Episode')

        # 前5个Episode
        print(f'\n前5个Episode样本:')
        for i, ep in enumerate(result['episodes'][:5], 1):
            print(f'  [{i}] {ep["episode_id"]}')
            print(f'      持续: {ep["duration"]/60:.1f}分钟')
            print(f'      边际: {ep["gross_edge_bps"]:.2f} bps')

    print('\n' + '='*70)
    print('✅ D1 Episode聚合完成')
    print('='*70)
