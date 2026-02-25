#!/usr/bin/env python3
"""
Script to remove logs management functionality from System.vue
"""

def remove_logs_management():
    file_path = 'frontend/src/views/System.vue'

    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    new_lines = []
    skip_until_end_div = 0
    in_logs_tab = False
    in_logs_functions = False
    skip_lines = 0

    i = 0
    while i < len(lines):
        line = lines[i]

        # Skip if we're in a skip block
        if skip_lines > 0:
            skip_lines -= 1
            i += 1
            continue

        # Remove logs tab from template (lines 350-430 approximately)
        if "v-if=\"activeTab === 'logs'\"" in line:
            in_logs_tab = True
            skip_until_end_div = 1
            i += 1
            continue

        if in_logs_tab:
            # Count div depth
            if '<div' in line:
                skip_until_end_div += line.count('<div')
            if '</div>' in line:
                skip_until_end_div -= line.count('</div>')

            if skip_until_end_div <= 0:
                in_logs_tab = False
            i += 1
            continue

        # Remove logs from tabs array
        if "{ id: 'logs', label: '日志管理' }" in line:
            i += 1
            continue

        # Remove logs from refreshModules array
        if "{ id: 'logs', name: '日志管理'" in line:
            i += 1
            continue

        # Remove logging state variables (around line 697-702)
        if 'const loggingEnabled = ref(' in line or \
           'const tradingLogs = ref(' in line or \
           'const logDisplayLines = ref(' in line or \
           'const lastLogUpdate = ref(' in line or \
           'let logRefreshInterval = null' in line:
            i += 1
            continue

        # Remove displayedLogs computed property
        if 'const displayedLogs = computed(' in line:
            # Skip until the closing })
            while i < len(lines) and '})' not in lines[i]:
                i += 1
            i += 1  # Skip the }) line
            continue

        # Remove logging functions
        if 'async function toggleLogging()' in line or \
           'async function refreshLogs()' in line or \
           'function clearLogs()' in line or \
           'function startLogRefresh()' in line or \
           'function stopLogRefresh()' in line:
            # Skip until the closing }
            brace_count = 0
            found_opening = False
            while i < len(lines):
                if '{' in lines[i]:
                    brace_count += lines[i].count('{')
                    found_opening = True
                if '}' in lines[i]:
                    brace_count -= lines[i].count('}')
                i += 1
                if found_opening and brace_count == 0:
                    break
            # Skip the empty line after function
            if i < len(lines) and lines[i].strip() == '':
                i += 1
            continue

        # Remove getLogClass and getLogLevelClass functions
        if 'function getLogClass(' in line or 'function getLogLevelClass(' in line:
            # Skip until the closing }
            brace_count = 0
            found_opening = False
            while i < len(lines):
                if '{' in lines[i]:
                    brace_count += lines[i].count('{')
                    found_opening = True
                if '}' in lines[i]:
                    brace_count -= lines[i].count('}')
                i += 1
                if found_opening and brace_count == 0:
                    break
            # Skip the empty line after function
            if i < len(lines) and lines[i].strip() == '':
                i += 1
            continue

        # Keep this line
        new_lines.append(line)
        i += 1

    # Write back
    with open(file_path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)

    removed_count = len(lines) - len(new_lines)
    print(f"Removed {removed_count} lines from {file_path}")
    print(f"Original: {len(lines)} lines")
    print(f"New: {len(new_lines)} lines")

if __name__ == '__main__':
    remove_logs_management()
