#!/usr/bin/env python3
"""
Clean up System.vue by removing RBAC, Security, and SSL related sections
"""
import re

def clean_system_vue():
    file_path = r'C:\app\hustle2026\frontend\src\views\System.vue'

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Remove RBAC tab section from template
    content = re.sub(
        r'<!-- 角色权限管理 -->.*?(?=<!-- 安全组件管理 -->)',
        '',
        content,
        flags=re.DOTALL
    )

    # Remove Security tab section from template
    content = re.sub(
        r'<!-- 安全组件管理 -->.*?(?=<!-- SSL证书管理 -->)',
        '',
        content,
        flags=re.DOTALL
    )

    # Remove SSL tab section from template
    content = re.sub(
        r'<!-- SSL证书管理 -->.*?(?=<div v-if="activeTab === \'version\'">)',
        '',
        content,
        flags=re.DOTALL
    )

    # Comment out security store import
    content = content.replace(
        "import { useSecurityStore } from '@/stores/security'",
        "// import { useSecurityStore } from '@/stores/security'"
    )

    # Comment out security store usage
    content = re.sub(
        r'const securityStore = useSecurityStore\(\)',
        '// const securityStore = useSecurityStore()',
        content
    )
    content = re.sub(
        r'const \{ components: securityComponents, enabledComponents \} = storeToRefs\(securityStore\)',
        '// const { components: securityComponents, enabledComponents } = storeToRefs(securityStore)',
        content
    )

    # Remove tabs from array
    content = re.sub(
        r",\s*\{\s*id:\s*'rbac',\s*label:\s*'角色权限管理'\s*\}",
        '',
        content
    )
    content = re.sub(
        r",\s*\{\s*id:\s*'security',\s*label:\s*'安全组件管理'\s*\}",
        '',
        content
    )
    content = re.sub(
        r",\s*\{\s*id:\s*'ssl',\s*label:\s*'SSL证书管理'\s*\}",
        '',
        content
    )

    # Remove navigation functions
    content = re.sub(
        r'function navigateToRbac\(\) \{[^}]+\}',
        '',
        content
    )
    content = re.sub(
        r'function navigateToSecurity\(\) \{[^}]+\}',
        '',
        content
    )
    content = re.sub(
        r'function navigateToSsl\(\) \{[^}]+\}',
        '',
        content
    )

    # Remove computed properties
    content = re.sub(
        r'const middlewareCount = computed\(\(\) =>[^)]+\)',
        '',
        content
    )
    content = re.sub(
        r'const protectionCount = computed\(\(\) =>[^)]+\)',
        '',
        content
    )

    # Remove helper functions
    content = re.sub(
        r'const getComponentTypeBadge = \(type\) => \{[^}]+\}',
        '',
        content,
        flags=re.DOTALL
    )
    content = re.sub(
        r'const getComponentTypeLabel = \(type\) => \{[^}]+\}',
        '',
        content,
        flags=re.DOTALL
    )

    # Remove security component statistics comment and related code
    content = re.sub(
        r'// 安全组件统计\s*\n',
        '',
        content
    )

    # Remove loadSecurityComponents call
    content = re.sub(
        r'\s*await securityStore\.fetchComponents\(\)',
        '',
        content
    )

    # Write back
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print("System.vue cleaned successfully")

if __name__ == "__main__":
    clean_system_vue()
