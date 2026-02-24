#!/usr/bin/env python3
"""
时间格式检查脚本 - UTC标准化审计工具
用途：扫描代码库中所有时间相关代码，识别非UTC时间使用场景
作者：系统架构团队
版本：1.0.0
"""

import os
import re
import json
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime


class TimeFormatChecker:
    """时间格式检查器"""

    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self.issues = []

        # 定义检查模式
        self.patterns = {
            # 严重问题：使用本地时间
            'datetime_now': {
                'pattern': r'datetime\.now\(\)',
                'severity': 'HIGH',
                'message': '使用本地时间 datetime.now()，应改为 datetime.utcnow()',
                'suggestion': 'datetime.utcnow()'
            },
            'date_today': {
                'pattern': r'date\.today\(\)',
                'severity': 'HIGH',
                'message': '使用本地日期 date.today()，应改为 datetime.utcnow().date()',
                'suggestion': 'datetime.utcnow().date()'
            },

            # 中等问题：时区处理不当
            'timestamp_without_tz': {
                'pattern': r'TIMESTAMP\s*\(',
                'severity': 'MEDIUM',
                'message': '使用 TIMESTAMP WITHOUT TIME ZONE，建议改为 TIMESTAMP WITH TIME ZONE',
                'suggestion': 'sa.TIMESTAMP(timezone=True)'
            },
            'strptime_no_tz': {
                'pattern': r'datetime\.strptime\([^)]+\)(?!\s*\.replace\(tzinfo)',
                'severity': 'MEDIUM',
                'message': '使用 strptime 解析时间但未指定时区',
                'suggestion': '添加 .replace(tzinfo=timezone.utc) 或使用 fromisoformat'
            },
            'replace_tzinfo_none': {
                'pattern': r'\.replace\(tzinfo=None\)',
                'severity': 'MEDIUM',
                'message': '手动移除时区信息，可能导致时区混淆',
                'suggestion': '保留时区信息或确保数据库支持时区'
            },

            # 轻微问题：时间显示格式
            'tolocalestring': {
                'pattern': r'\.toLocaleString\(',
                'severity': 'LOW',
                'message': '使用 toLocaleString 可能导致不同用户看到不同格式',
                'suggestion': '统一使用 ISO 格式或明确标注时区'
            },
            'new_date_no_tz': {
                'pattern': r'new Date\([^)]*\)(?!\.toISOString)',
                'severity': 'LOW',
                'message': '使用 new Date() 依赖浏览器时区',
                'suggestion': '使用 ISO 格式字符串或明确时区转换'
            }
        }

    def scan_file(self, file_path: Path) -> List[Dict[str, Any]]:
        """扫描单个文件"""
        issues = []

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            for line_num, line in enumerate(lines, 1):
                for check_name, check_config in self.patterns.items():
                    if re.search(check_config['pattern'], line):
                        issues.append({
                            'file': str(file_path.relative_to(self.project_root)),
                            'line': line_num,
                            'code': line.strip(),
                            'check': check_name,
                            'severity': check_config['severity'],
                            'message': check_config['message'],
                            'suggestion': check_config['suggestion']
                        })

        except Exception as e:
            print(f"Error scanning {file_path}: {e}")

        return issues

    def scan_directory(self, extensions: List[str] = None) -> List[Dict[str, Any]]:
        """扫描整个目录"""
        if extensions is None:
            extensions = ['.py', '.js', '.vue', '.ts', '.tsx']

        all_issues = []

        # 排除目录
        exclude_dirs = {
            'node_modules', 'venv', '__pycache__', '.git',
            'dist', 'build', '.pytest_cache', 'alembic'
        }

        for ext in extensions:
            for file_path in self.project_root.rglob(f'*{ext}'):
                # 检查是否在排除目录中
                if any(excluded in file_path.parts for excluded in exclude_dirs):
                    continue

                issues = self.scan_file(file_path)
                all_issues.extend(issues)

        return all_issues

    def generate_report(self, issues: List[Dict[str, Any]], output_format: str = 'json') -> str:
        """生成报告"""
        # 按严重程度分组
        grouped = {'HIGH': [], 'MEDIUM': [], 'LOW': []}
        for issue in issues:
            grouped[issue['severity']].append(issue)

        if output_format == 'json':
            return json.dumps({
                'scan_time': datetime.utcnow().isoformat(),
                'total_issues': len(issues),
                'by_severity': {
                    'HIGH': len(grouped['HIGH']),
                    'MEDIUM': len(grouped['MEDIUM']),
                    'LOW': len(grouped['LOW'])
                },
                'issues': issues
            }, indent=2, ensure_ascii=False)

        elif output_format == 'markdown':
            report = f"""# 时间格式检查报告

**扫描时间：** {datetime.utcnow().isoformat()}
**发现问题总数：** {len(issues)}

## 问题统计

| 严重程度 | 数量 |
|---------|------|
| 🔴 HIGH | {len(grouped['HIGH'])} |
| 🟡 MEDIUM | {len(grouped['MEDIUM'])} |
| 🟢 LOW | {len(grouped['LOW'])} |

---

## 详细问题列表

"""
            for severity in ['HIGH', 'MEDIUM', 'LOW']:
                if grouped[severity]:
                    emoji = {'HIGH': '🔴', 'MEDIUM': '🟡', 'LOW': '🟢'}[severity]
                    report += f"\n### {emoji} {severity} 优先级问题\n\n"

                    for issue in grouped[severity]:
                        report += f"""#### {issue['file']}:{issue['line']}

**问题代码：**
```
{issue['code']}
```

**问题描述：** {issue['message']}
**修复建议：** `{issue['suggestion']}`

---

"""
            return report

        else:
            raise ValueError(f"Unsupported format: {output_format}")

    def run(self, output_file: str = None, output_format: str = 'markdown'):
        """运行检查"""
        print(f"[*] Starting scan: {self.project_root}")
        print(f"[*] File types: .py, .js, .vue, .ts, .tsx")
        print()

        issues = self.scan_directory()

        print(f"[+] Scan completed!")
        print(f"[*] Total issues: {len(issues)}")
        print(f"   - HIGH: {len([i for i in issues if i['severity'] == 'HIGH'])}")
        print(f"   - MEDIUM: {len([i for i in issues if i['severity'] == 'MEDIUM'])}")
        print(f"   - LOW: {len([i for i in issues if i['severity'] == 'LOW'])}")
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

    parser = argparse.ArgumentParser(description='时间格式检查工具')
    parser.add_argument('--project-root', default='.', help='项目根目录')
    parser.add_argument('--output', '-o', help='输出文件路径')
    parser.add_argument('--format', '-f', choices=['json', 'markdown'], default='markdown', help='输出格式')

    args = parser.parse_args()

    checker = TimeFormatChecker(args.project_root)
    checker.run(output_file=args.output, output_format=args.format)
