#!/usr/bin/env python3
"""
Clean up System.vue by removing RBAC, Security, and SSL related sections
"""

def clean_system_vue():
    file_path = r'C:\app\hustle2026\frontend\src\views\System.vue'

    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # Find and mark lines to remove
    remove_ranges = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # Find RBAC section (starts at line 71, ends before security section)
        if "<!-- 角色权限管理 -->" in line:
            start = i
            # Find the end (next major section or version section)
            j = i + 1
            while j < len(lines) and "<!-- 安全组件管理 -->" not in lines[j]:
                j += 1
            remove_ranges.append((start, j))
            i = j
            continue

        # Find Security section
        if "<!-- 安全组件管理 -->" in line:
            start = i
            j = i + 1
            while j < len(lines) and "<!-- SSL证书管理 -->" not in lines[j]:
                j += 1
            remove_ranges.append((start, j))
            i = j
            continue

        # Find SSL section
        if "<!-- SSL证书管理 -->" in line:
            start = i
            j = i + 1
            # Find next section (version)
            while j < len(lines) and "v-if=\"activeTab === 'version'\"" not in lines[j]:
                j += 1
            remove_ranges.append((start, j))
            i = j
            continue

        i += 1

    # Remove the marked ranges (in reverse order to maintain indices)
    for start, end in reversed(remove_ranges):
        del lines[start:end]

    # Now remove related code in script section
    new_lines = []
    skip_until = None

    for i, line in enumerate(lines):
        # Skip security store import
        if "import { useSecurityStore }" in line:
            new_lines.append("// " + line)  # Comment it out
            continue

        # Skip security store usage
        if "const securityStore = useSecurityStore()" in line or \
           "const { components: securityComponents" in line:
            new_lines.append("// " + line)
            continue

        # Remove rbac, security, ssl from tabs array
        if "{ id: 'rbac'" in line or \
           "{ id: 'security'" in line or \
           "{ id: 'ssl'" in line:
            continue

        # Skip navigation functions
        if skip_until:
            if i >= skip_until:
                skip_until = None
            else:
                continue

        if "function navigateToRbac()" in line or \
           "function navigateToSecurity()" in line or \
           "function navigateToSsl()" in line:
            # Skip this function and next 2 lines
            skip_until = i + 3
            continue

        # Skip computed properties
        if "const middlewareCount = computed" in line or \
           "const protectionCount = computed" in line:
            # Skip until closing parenthesis
            skip_until = i + 3
            continue

        # Skip helper functions
        if "const getComponentTypeBadge" in line or \
           "const getComponentTypeLabel" in line:
            # Skip until closing brace
            j = i
            while j < len(lines) and "}" not in lines[j]:
                j += 1
            skip_until = j + 1
            continue

        new_lines.append(line)

    # Write back
    with open(file_path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)

    print("System.vue cleaned successfully")
    print(f"Removed {len(lines) - len(new_lines)} lines")

if __name__ == "__main__":
    clean_system_vue()
