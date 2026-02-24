#!/usr/bin/env python3
"""
轮询残留检测脚本
用途：扫描前端代码中的轮询逻辑，识别未完成WebSocket改造的组件
作者：系统架构团队
版本：1.0.0
"""

import os
import re
import json
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime


class PollingDetector:
    """轮询检测器"""

    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self.issues = []

        # 定义检测模式
        self.patterns = {
            'setInterval': {
                'pattern': r'setInterval\s*\(\s*([^,]+)\s*,\s*(\d+)\s*\)',
                'severity': 'HIGH',
                'message': '使用setInterval进行轮询'
            },
            'setTimeout_recursive': {
                'pattern': r'setTimeout\s*\(\s*([^,]+)\s*,\s*(\d+)\s*\)',
                'severity': 'MEDIUM',
                'message': '使用setTimeout可能进行递归轮询'
            },
            'fetch_in_interval': {
                'pattern': r'(fetch|axios|api\.(get|post))\s*\([^)]+\).*setInterval',
                'severity': 'HIGH',
                'message': 'HTTP请求在定时器中执行'
            }
        }

    def scan_file(self, file_path: Path) -> List[Dict[str, Any]]:
        """扫描单个文件"""
        issues = []

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.split('\n')

            # 检测setInterval
            for match in re.finditer(self.patterns['setInterval']['pattern'], content):
                line_num = content[:match.start()].count('\n') + 1
                interval_ms = int(match.group(2))
                interval_sec = interval_ms / 1000

                # 获取上下文代码
                context_start = max(0, line_num - 3)
                context_end = min(len(lines), line_num + 2)
                context = '\n'.join(lines[context_start:context_end])

                issues.append({
                    'file': str(file_path.relative_to(self.project_root)),
                    'line': line_num,
                    'type': 'setInterval',
                    'interval_ms': interval_ms,
                    'interval_sec': interval_sec,
                    'severity': 'HIGH' if interval_sec <= 5 else 'MEDIUM',
                    'code': lines[line_num - 1].strip() if line_num <= len(lines) else '',
                    'context': context,
                    'message': f'使用setInterval进行{interval_sec}秒轮询'
                })

            # 检测setTimeout
            for match in re.finditer(self.patterns['setTimeout_recursive']['pattern'], content):
                line_num = content[:match.start()].count('\n') + 1
                interval_ms = int(match.group(2))
                interval_sec = interval_ms / 1000

                # 检查是否在函数内部调用自身（递归轮询）
                context_start = max(0, line_num - 10)
                context_end = min(len(lines), line_num + 5)
                context = '\n'.join(lines[context_start:context_end])

                # 简单检测递归模式
                if 'function' in context or 'const' in context or 'async' in context:
                    issues.append({
                        'file': str(file_path.relative_to(self.project_root)),
                        'line': line_num,
                        'type': 'setTimeout',
                        'interval_ms': interval_ms,
                        'interval_sec': interval_sec,
                        'severity': 'MEDIUM',
                        'code': lines[line_num - 1].strip() if line_num <= len(lines) else '',
                        'context': context,
                        'message': f'使用setTimeout可能进行{interval_sec}秒递归轮询'
                    })

        except Exception as e:
            print(f"Error scanning {file_path}: {e}")

        return issues

    def scan_directory(self, extensions: List[str] = None) -> List[Dict[str, Any]]:
        """扫描整个目录"""
        if extensions is None:
            extensions = ['.vue', '.js', '.ts', '.jsx', '.tsx']

        all_issues = []

        # 排除目录
        exclude_dirs = {
            'node_modules', 'dist', 'build', '.git',
            '__pycache__', '.pytest_cache'
        }

        for ext in extensions:
            for file_path in self.project_root.rglob(f'*{ext}'):
                # 检查是否在排除目录中
                if any(excluded in file_path.parts for excluded in exclude_dirs):
                    continue

                issues = self.scan_file(file_path)
                all_issues.extend(issues)

        return all_issues

    def generate_report(self, issues: List[Dict[str, Any]], output_format: str = 'markdown') -> str:
        """生成报告"""
        # 按严重程度和频率分组
        high_freq = [i for i in issues if i['interval_sec'] <= 1]
        medium_freq = [i for i in issues if 1 < i['interval_sec'] <= 5]
        low_freq = [i for i in issues if i['interval_sec'] > 5]

        if output_format == 'json':
            return json.dumps({
                'scan_time': datetime.utcnow().isoformat(),
                'total_issues': len(issues),
                'by_frequency': {
                    'high': len(high_freq),
                    'medium': len(medium_freq),
                    'low': len(low_freq)
                },
                'issues': issues
            }, indent=2, ensure_ascii=False)

        elif output_format == 'markdown':
            report = f"""# 轮询残留检测报告

**扫描时间：** {datetime.utcnow().isoformat()}
**发现问题总数：** {len(issues)}

## 问题统计

| 轮询频率 | 数量 | 优先级 |
|---------|------|--------|
| 🔴 高频 (≤1秒) | {len(high_freq)} | 紧急改造 |
| 🟡 中频 (1-5秒) | {len(medium_freq)} | 优先改造 |
| 🟢 低频 (>5秒) | {len(low_freq)} | 可选改造 |

---

## 详细问题列表

"""
            # 按文件分组
            issues_by_file = {}
            for issue in issues:
                file_name = issue['file']
                if file_name not in issues_by_file:
                    issues_by_file[file_name] = []
                issues_by_file[file_name].append(issue)

            # 按频率排序文件
            sorted_files = sorted(issues_by_file.items(),
                                key=lambda x: min(i['interval_sec'] for i in x[1]))

            for file_name, file_issues in sorted_files:
                report += f"\n### 📄 {file_name}\n\n"

                for issue in sorted(file_issues, key=lambda x: x['interval_sec']):
                    emoji = '🔴' if issue['interval_sec'] <= 1 else ('🟡' if issue['interval_sec'] <= 5 else '🟢')
                    report += f"""#### {emoji} 第{issue['line']}行 - {issue['interval_sec']}秒轮询

**问题代码：**
```javascript
{issue['code']}
```

**上下文：**
```javascript
{issue['context']}
```

**改造建议：**
- 将HTTP轮询改为WebSocket实时推送
- 使用market store的WebSocket连接
- 订阅相应的消息类型

---

"""

            # 添加改造优先级建议
            report += f"""
## 改造优先级建议

### 🔴 紧急改造 (高频轮询 ≤1秒)

共 {len(high_freq)} 处，严重影响性能和服务器负载。

**文件列表：**
"""
            high_freq_files = set(i['file'] for i in high_freq)
            for file_name in sorted(high_freq_files):
                count = len([i for i in high_freq if i['file'] == file_name])
                report += f"- {file_name} ({count}处)\n"

            report += f"""
### 🟡 优先改造 (中频轮询 1-5秒)

共 {len(medium_freq)} 处，影响用户体验和资源消耗。

**文件列表：**
"""
            medium_freq_files = set(i['file'] for i in medium_freq)
            for file_name in sorted(medium_freq_files):
                count = len([i for i in medium_freq if i['file'] == file_name])
                report += f"- {file_name} ({count}处)\n"

            report += f"""
### 🟢 可选改造 (低频轮询 >5秒)

共 {len(low_freq)} 处，影响较小，可后续优化。

**文件列表：**
"""
            low_freq_files = set(i['file'] for i in low_freq)
            for file_name in sorted(low_freq_files):
                count = len([i for i in low_freq if i['file'] == file_name])
                report += f"- {file_name} ({count}处)\n"

            report += """
---

## WebSocket改造指南

### 1. 引入market store

```javascript
import { useMarketStore } from '@/stores/market'

const marketStore = useMarketStore()
```

### 2. 建立WebSocket连接

```javascript
onMounted(() => {
  marketStore.connect()
})

onUnmounted(() => {
  // 如果需要，可以断开连接
  // marketStore.disconnect()
})
```

### 3. 监听数据更新

```javascript
import { watch } from 'vue'

watch(() => marketStore.marketData, (newData) => {
  if (newData) {
    // 处理新数据
    console.log('收到市场数据:', newData)
  }
})
```

### 4. 移除轮询代码

```javascript
// ❌ 删除这些代码
// const timer = setInterval(fetchData, 1000)
// onUnmounted(() => clearInterval(timer))
```

---

**报告生成时间：** {datetime.utcnow().isoformat()}
"""
            return report

        else:
            raise ValueError(f"Unsupported format: {output_format}")

    def run(self, output_file: str = None, output_format: str = 'markdown'):
        """运行检查"""
        print(f"[*] Starting scan: {self.project_root}")
        print(f"[*] File types: .vue, .js, .ts, .jsx, .tsx")
        print()

        issues = self.scan_directory()

        print(f"[+] Scan completed!")
        print(f"[*] Total polling issues found: {len(issues)}")

        # 统计
        high_freq = len([i for i in issues if i['interval_sec'] <= 1])
        medium_freq = len([i for i in issues if 1 < i['interval_sec'] <= 5])
        low_freq = len([i for i in issues if i['interval_sec'] > 5])

        print(f"   - HIGH frequency (<=1s): {high_freq}")
        print(f"   - MEDIUM frequency (1-5s): {medium_freq}")
        print(f"   - LOW frequency (>5s): {low_freq}")
        print()

        report = self.generate_report(issues, output_format)

        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"[+] Report saved to: {output_file}")
        else:
            print(report)

        return issues


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='轮询残留检测工具')
    parser.add_argument('--project-root', default='.', help='项目根目录')
    parser.add_argument('--output', '-o', help='输出文件路径')
    parser.add_argument('--format', '-f', choices=['json', 'markdown'], default='markdown', help='输出格式')

    args = parser.parse_args()

    detector = PollingDetector(args.project_root)
    detector.run(output_file=args.output, output_format=args.format)
