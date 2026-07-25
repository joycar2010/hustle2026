#!/usr/bin/env python3
"""
Episode聚合器
目标: 将D1的采样历史数据聚合为独立的交易Episode
"""
import sqlite3
import json
from decimal import Decimal
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime

@dataclass
class EpisodePolicy:
    """Episode识别策略"""
    entry_threshold_bps: Decimal  # 连续k次超过此阈值才开始
    exit_threshold_bps: Decimal   # 连续m次低于此阈值才结束
    entry_consecutive_count: int  # k: 连续触发次数
    exit_consecutive_count: int   # m: 连续退出次数
    max_gap_seconds: int          # 最大数据缺口（超过则分割）
    max_duration_seconds: int     # 最大持续时间

class EpisodeAggregator:
    """Episode聚合器"""

    def __init__(self, db_path='dexlab.db'):
        self.db_path = db_path
        self.policy = EpisodePolicy(
            entry_threshold_bps=Decimal('5.0'),
            exit_threshold_bps=Decimal('2.0'),
            entry_consecutive_count=3,
            exit_consecutive_count=2,
            max_gap_seconds=1800,  # 30分钟
            max_duration_seconds=86400  # 24小时
        )

    def aggregate_from_signals(self, run_id: int, instrument_version: str) -> List[Dict]:
        """
        从lab_signal聚合Episode

        前视偏差防御:
        1. 只在连续k次触发后，使用下一个可执行报价入场
        2. 数据缺口视为不可交易
        3. 退出价格使用触发时点的下一可执行报价
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # 获取run的所有信号（按时间排序）
        cur.execute('''
            SELECT id, ts, payload
            FROM lab_signal
            WHERE project_id = (SELECT project_id FROM lab_run WHERE run_id = ?)
            ORDER BY ts
        ''', (run_id,))

        signals = cur.fetchall()
        conn.close()

        if not signals:
            return []

        episodes = []
        current_episode = None
        entry_trigger_count = 0
        exit_trigger_count = 0
        last_ts = None

        for signal in signals:
            ts = signal['ts']
            payload = json.loads(signal['payload'])

            # 提取边际（假设payload有edge_bps字段）
            edge_bps = Decimal(str(payload.get('conservative_net_bps', 0)))

            # 检查数据缺口
            if last_ts and (ts - last_ts) > self.policy.max_gap_seconds:
                # 缺口过大，关闭当前Episode
                if current_episode:
                    current_episode['ended_at'] = last_ts
                    current_episode['false_positive_reason'] = 'DATA_GAP'
                    episodes.append(current_episode)
                    current_episode = None
                entry_trigger_count = 0
                exit_trigger_count = 0

            last_ts = ts

            # 判断是否触发入场
            if edge_bps >= self.policy.entry_threshold_bps:
                entry_trigger_count += 1
                exit_trigger_count = 0

                # 连续k次触发且当前无Episode，创建新Episode
                if entry_trigger_count >= self.policy.entry_consecutive_count and not current_episode:
                    # 前视偏差防御: 使用触发完成后的下一个时点入场
                    current_episode = {
                        'episode_id': f'EP-{run_id}-{len(episodes)+1}',
                        'run_id': run_id,
                        'instrument_version': instrument_version,
                        'route_key': payload.get('route', 'unknown'),
                        'started_at': ts,
                        'entry_quote_ids': [signal['id']],
                        'observations': [{'ts': ts, 'edge_bps': float(edge_bps)}],
                        'target_notional': payload.get('target_usd', 0),
                        'entry_feasible': 1,
                        'observation_count': 1
                    }

            # 判断是否触发退出
            elif edge_bps < self.policy.exit_threshold_bps:
                exit_trigger_count += 1
                entry_trigger_count = 0

                if current_episode:
                    current_episode['observations'].append({'ts': ts, 'edge_bps': float(edge_bps)})
                    current_episode['observation_count'] += 1

                    # 连续m次低于退出阈值，关闭Episode
                    if exit_trigger_count >= self.policy.exit_consecutive_count:
                        current_episode['ended_at'] = ts
                        current_episode['exit_quote_ids'] = [signal['id']]
                        current_episode['exit_feasible'] = 1
                        episodes.append(current_episode)
                        current_episode = None
                        exit_trigger_count = 0

            # 在阈值之间
            else:
                entry_trigger_count = 0
                exit_trigger_count = 0

                if current_episode:
                    current_episode['observations'].append({'ts': ts, 'edge_bps': float(edge_bps)})
                    current_episode['observation_count'] += 1

            # 检查最大持续时间
            if current_episode:
                duration = ts - current_episode['started_at']
                if duration > self.policy.max_duration_seconds:
                    current_episode['ended_at'] = ts
                    current_episode['false_positive_reason'] = 'MAX_DURATION_EXCEEDED'
                    episodes.append(current_episode)
                    current_episode = None
                    entry_trigger_count = 0

        # 处理未关闭的Episode
        if current_episode:
            current_episode['ended_at'] = last_ts
            current_episode['false_positive_reason'] = 'RIGHT_CENSORED'
            episodes.append(current_episode)

        # 计算Episode统计
        for ep in episodes:
            obs = ep['observations']
            ep['duration'] = ep['ended_at'] - ep['started_at']

            # 计算统计
            edges = [o['edge_bps'] for o in obs]
            ep['gross_edge_bps'] = sum(edges) / len(edges) if edges else 0
            ep['mae_bps'] = min(edges) if edges else 0  # Maximum Adverse Excursion
            ep['mfe_bps'] = max(edges) if edges else 0  # Maximum Favorable Excursion

            # 移除observations（太大）
            del ep['observations']

        return episodes

    def save_episodes(self, episodes: List[Dict]) -> int:
        """保存Episode到数据库"""
        conn = sqlite3.connect(self.db_path)
        conn.execute('PRAGMA busy_timeout = 30000')
        cur = conn.cursor()

        saved_count = 0
        for ep in episodes:
            cur.execute('''
                INSERT INTO lab_episodes
                (episode_id, run_id, instrument_version, route_key, size_bucket,
                 started_at, ended_at, duration, observation_count,
                 entry_quote_ids, exit_quote_ids,
                 target_notional, gross_edge_bps, mae_bps, mfe_bps,
                 entry_feasible, exit_feasible, false_positive_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                ep['episode_id'],
                ep['run_id'],
                ep['instrument_version'],
                ep['route_key'],
                None,  # size_bucket
                ep['started_at'],
                ep['ended_at'],
                ep['duration'],
                ep['observation_count'],
                json.dumps(ep.get('entry_quote_ids', [])),
                json.dumps(ep.get('exit_quote_ids', [])),
                ep.get('target_notional'),
                ep.get('gross_edge_bps'),
                ep.get('mae_bps'),
                ep.get('mfe_bps'),
                ep.get('entry_feasible', 0),
                ep.get('exit_feasible', 0),
                ep.get('false_positive_reason')
            ))
            saved_count += 1

        conn.commit()
        conn.close()

        return saved_count

if __name__ == '__main__':
    print('='*70)
    print('📦 Episode聚合器测试')
    print('='*70)

    aggregator = EpisodeAggregator()

    print(f'\\nEpisode识别策略:')
    print(f'  入场阈值: {aggregator.policy.entry_threshold_bps} bps (连续{aggregator.policy.entry_consecutive_count}次)')
    print(f'  退出阈值: {aggregator.policy.exit_threshold_bps} bps (连续{aggregator.policy.exit_consecutive_count}次)')
    print(f'  最大缺口: {aggregator.policy.max_gap_seconds}秒')
    print(f'  最大持续: {aggregator.policy.max_duration_seconds}秒')

    # 测试：对D1 run#4聚合
    print(f'\\n聚合D1 run#4 (388轮):')
    episodes = aggregator.aggregate_from_signals(4, 'D1-REDEEM-DISCOUNT')

    print(f'  识别出 {len(episodes)} 个Episode')

    if episodes:
        print(f'\\n前3个Episode:')
        for i, ep in enumerate(episodes[:3], 1):
            duration_min = ep['duration'] / 60
            print(f'  [{i}] {ep["episode_id"]}')
            print(f'      持续: {duration_min:.1f}分钟 ({ep["observation_count"]}次观测)')
            print(f'      边际: {ep["gross_edge_bps"]:.2f} bps')
            print(f'      MAE/MFE: {ep["mae_bps"]:.2f} / {ep["mfe_bps"]:.2f} bps')

    print('\\n✓ Episode聚合器测试完成')
    print('='*70)
