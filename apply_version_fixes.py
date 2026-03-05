"""
自动修复system.py的版本管理功能

使用方法：
python apply_version_fixes.py
"""

import re
from pathlib import Path


def apply_fixes():
    system_py = Path("c:/app/hustle2026/backend/app/api/v1/system.py")

    if not system_py.exists():
        print(f"错误：找不到文件 {system_py}")
        return False

    # 读取文件
    with open(system_py, 'r', encoding='utf-8') as f:
        content = f.read()

    # 备份原文件
    backup_file = system_py.with_suffix('.py.backup')
    with open(backup_file, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"✓ 已备份原文件到: {backup_file}")

    # 修复1：确保导入了必要的模块
    if 'from app.services.version_service import version_service' not in content:
        # 在导入部分添加
        import_pattern = r'(from app\.tasks\.redis_monitor import redis_monitor)'
        replacement = r'\1\nfrom app.services.version_service import version_service'
        content = re.sub(import_pattern, replacement, content)
        print("✓ 添加了version_service导入")

    if 'import re' not in content:
        # 在导入部分添加re模块
        import_pattern = r'(import os)'
        replacement = r'\1\nimport re'
        content = re.sub(import_pattern, replacement, content)
        print("✓ 添加了re模块导入")

    # 修复2：替换push_to_github函数
    push_pattern = r'@router\.post\("/github/push"\).*?(?=@router\.post\("/github/rollback"\)|@router\.delete)'

    new_push_function = '''@router.post("/github/push")
async def push_to_github(
    remark: Optional[str] = Body(None, embed=True),
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """Push current version to GitHub and increment version numbers"""
    try:
        import subprocess

        # Get current branch name
        branch_result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=".."
        )

        if branch_result.returncode != 0:
            raise Exception(f"Failed to get current branch: {branch_result.stderr}")

        current_branch = branch_result.stdout.strip()

        # Check if there are changes to commit
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=".."
        )

        if status_result.returncode != 0:
            raise Exception(f"Git status failed: {status_result.stderr}")

        has_changes = bool(status_result.stdout.strip())

        if has_changes:
            # Increment version numbers BEFORE commit
            new_versions = version_service.increment_on_backup()

            # Create commit message with version info
            commit_message = f"Version {new_versions['frontend_version']}/{new_versions['backend_version']}"
            if remark:
                commit_message += f": {remark}"

            # Add all changes
            add_result = subprocess.run(
                ["git", "add", "-A"],
                capture_output=True,
                text=True,
                cwd=".."
            )

            if add_result.returncode != 0:
                raise Exception(f"Git add failed: {add_result.stderr}")

            # Commit changes
            commit_result = subprocess.run(
                ["git", "commit", "-m", commit_message],
                capture_output=True,
                text=True,
                cwd=".."
            )

            if commit_result.returncode != 0:
                raise Exception(f"Git commit failed: {commit_result.stderr}")

        # Pull latest changes from remote
        pull_result = subprocess.run(
            ["git", "pull", "--rebase", "origin", current_branch],
            capture_output=True,
            text=True,
            cwd=".."
        )

        # If pull fails due to conflicts, provide detailed error
        if pull_result.returncode != 0:
            if "CONFLICT" in pull_result.stdout or "CONFLICT" in pull_result.stderr:
                raise Exception(
                    "分支冲突：请先拉取最新代码并解决冲突。\\n"
                    "建议操作：\\n"
                    "1. 在本地执行 git pull origin " + current_branch + "\\n"
                    "2. 解决冲突后重新推送"
                )
            else:
                raise Exception(f"Git pull failed: {pull_result.stderr}")

        # Push to GitHub
        push_result = subprocess.run(
            ["git", "push", "origin", current_branch],
            capture_output=True,
            text=True,
            cwd=".."
        )

        if push_result.returncode != 0:
            error_msg = push_result.stderr.lower()

            # Provide specific error messages
            if "authentication" in error_msg or "permission denied" in error_msg:
                raise Exception(
                    "GitHub 认证失败：\\n"
                    "1. 检查 GitHub Personal Access Token 是否有效\\n"
                    "2. 确认 token 具有 'repo' 权限\\n"
                    "3. 验证 Git 配置中的凭据是否正确"
                )
            elif "rate limit" in error_msg:
                raise Exception(
                    "GitHub API 限流：\\n"
                    "请稍后再试，或检查 API 调用频率"
                )
            elif "rejected" in error_msg:
                raise Exception(
                    "推送被拒绝：\\n"
                    "远程分支有新提交，请先拉取最新代码"
                )
            else:
                raise Exception(f"Git push failed: {push_result.stderr}")

        # Get updated versions
        versions = version_service.get_versions()

        return {
            "message": f"Successfully pushed to GitHub branch: {current_branch}",
            "branch": current_branch,
            "frontend_version": versions["frontend_version"],
            "backend_version": versions["backend_version"],
            "output": push_result.stdout
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to push to GitHub: {str(e)}"
        )


'''

    if re.search(push_pattern, content, re.DOTALL):
        content = re.sub(push_pattern, new_push_function, content, flags=re.DOTALL)
        print("✓ 已更新push_to_github函数")
    else:
        print("⚠ 警告：未找到push_to_github函数，可能需要手动修改")

    # 保存修改后的文件
    with open(system_py, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"\n✓ 修复完成！修改已保存到: {system_py}")
    print(f"✓ 原文件备份在: {backup_file}")
    print("\n注意：由于函数较复杂，建议手动检查修改后的文件")
    print("特别是rollback_version和delete_github_backup函数需要手动修改")

    return True


if __name__ == "__main__":
    print("=" * 60)
    print("系统版本管理模块自动修复工具")
    print("=" * 60)
    print()

    try:
        success = apply_fixes()
        if success:
            print("\n修复脚本执行成功！")
            print("\n后续步骤：")
            print("1. 检查 backend/app/api/v1/system.py 的修改")
            print("2. 手动修改 rollback_version 函数（第757行）")
            print("3. 手动修改 delete_github_backup 函数（第798行）")
            print("4. 重启后端服务")
            print("5. 修改前端 System.vue")
            print("6. 测试功能")
        else:
            print("\n修复脚本执行失败！")
    except Exception as e:
        print(f"\n错误：{e}")
        import traceback
        traceback.print_exc()
