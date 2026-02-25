#!/usr/bin/env python3
"""
Clean up System.vue by removing RBAC, Security, and SSL related sections
"""

def clean_system_vue():
    file_path = r'C:\app\hustle2026\frontend\src\views\System.vue'

    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    new_lines = []
    skip_mode = None
    skip_depth = 0

    i = 0
    while i < len(lines):
        line = lines[i]

        # Skip RBAC section
        if "<!-- 角色权限管理 -->" in line:
            # Skip until we find the next major section
            while i < len(lines) and "<!-- 安全组件管理 -->" not in lines[i]:
                i += 1
            continue

        # Skip Security section
        if "<!-- 安全组件管理 -->" in line:
            while i < len(lines) and "<!-- SSL证书管理 -->" not in lines[i]:
                i += 1
            continue

        # Skip SSL section
        if "<!-- SSL证书管理 -->" in line:
            while i < len(lines) and "v-if=\"activeTab === 'version'\"" not in lines[i]:
                i += 1
            continue

        # Comment out security store import
        if "import { useSecurityStore }" in line:
            new_lines.append("// " + line)
            i += 1
            continue

        # Comment out security store usage
        if "const securityStore = useSecurityStore()" in line or \
           "const { components: securityComponents" in line:
            new_lines.append("// " + line)
            i += 1
            continue

        # Remove tabs from array
        if "{ id: 'rbac'" in line or \
           "{ id: 'security'" in line or \
           "{ id: 'ssl'" in line:
            i += 1
            continue

        # Skip navigation functions
        if "function navigateToRbac()" in line:
            while i < len(lines) and "}" not in lines[i]:
                i += 1
            i += 1  # Skip the closing brace
            continue

        if "function navigateToSecurity()" in line:
            while i < len(lines) and "}" not in lines[i]:
                i += 1
            i += 1
            continue

        if "function navigateToSsl()" in line:
            while i < len(lines) and "}" not in lines[i]:
                i += 1
            i += 1
            continue

        # Skip computed properties
        if "const middlewareCount = computed" in line:
            # Skip until we find the closing parenthesis and newline
            depth = 0
            while i < len(lines):
                if "(" in lines[i]:
                    depth += lines[i].count("(")
                if ")" in lines[i]:
                    depth -= lines[i].count(")")
                i += 1
                if depth == 0:
                    break
            continue

        if "const protectionCount = computed" in line:
            depth = 0
            while i < len(lines):
                if "(" in lines[i]:
                    depth += lines[i].count("(")
                if ")" in lines[i]:
                    depth -= lines[i].count(")")
                i += 1
                if depth == 0:
                    break
            continue

        # Skip helper functions
        if "const getComponentTypeBadge" in line:
            depth = 0
            started = False
            while i < len(lines):
                if "{" in lines[i]:
                    depth += lines[i].count("{")
                    started = True
                if "}" in lines[i]:
                    depth -= lines[i].count("}")
                i += 1
                if started and depth == 0:
                    break
            continue

        if "const getComponentTypeLabel" in line:
            depth = 0
            started = False
            while i < len(lines):
                if "{" in lines[i]:
                    depth += lines[i].count("{")
                    started = True
                if "}" in lines[i]:
                    depth -= lines[i].count("}")
                i += 1
                if started and depth == 0:
                    break
            continue

        # Skip security component statistics comment
        if "// 安全组件统计" in line:
            i += 1
            continue

        # Skip loadSecurityComponents call
        if "await securityStore.fetchComponents()" in line:
            i += 1
            continue

        # Keep this line
        new_lines.append(line)
        i += 1

    # Write back
    with open(file_path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)

    print(f"System.vue cleaned successfully")
    print(f"Original lines: {len(lines)}, New lines: {len(new_lines)}")

if __name__ == "__main__":
    clean_system_vue()
