#!/usr/bin/env python3
"""
精确修改system.py的版本管理函数

此脚本会：
1. 备份原文件
2. 精确替换push_to_github函数
3. 精确替换rollback_version函数
4. 精确替换delete_version函数
"""

import re
from pathlib import Path
import shutil

def backup_file(file_path):
    """备份文件"""
    backup_path = file_path.with_suffix('.py.backup')
    shutil.copy2(file_path, backup_path)
    print(f"✓ 已备份到: {backup_path}")
    return backup_path

def read_file(file_path):
    """读取文件"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()

def write_file(file_path, content):
    """写入文件"""
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

def replace_push_function(content):
    """替换push_to_github函数"""
    # 找到函数开始和结束位置
    start_pattern = r'@router\.post\("/github/push"\)\s*\nasync def push_to_github\('

    # 找到下一个@router装饰器作为结束标记
    end_pattern = r'\n\n@router\.post\("/github/rollback"\)'

    new_function = '''@router.post("/github/push")
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


@router.post("/github/rollback")'''

    # 使用正则表达式查找并替换
    pattern = r'@router\.post\("/github/push"\).*?(?=\n\n@router\.post\("/github/rollback"\))'

    if re.search(pattern, content, re.DOTALL):
        content = re.sub(pattern, new_function, content, flags=re.DOTALL)
        print("✓ 已替换push_to_github函数")
        return content, True
    else:
        print("⚠ 未找到push_to_github函数")
        return content, False

def replace_rollback_function(content):
    """替换rollback_version函数"""

    new_function = '''@router.post("/github/rollback")
async def rollback_version(
    request: RollbackRequest,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, str]:
    """Rollback to a specific version and restore version numbers"""
    try:
        import subprocess

        # Use hash if provided, otherwise use version (for backward compatibility)
        target = request.hash or request.version
        if not target:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Either hash or version must be provided"
            )

        # Get commit message to extract version numbers
        log_result = subprocess.run(
            ["git", "log", "-1", "--pretty=format:%s", target],
            capture_output=True,
            text=True,
            cwd=".."
        )

        if log_result.returncode != 0:
            raise Exception(f"Failed to get commit info: {log_result.stderr}")

        commit_message = log_result.stdout.strip()

        # Extract version numbers from commit message (format: "Version X.Y.Z/A.B.C")
        version_pattern = r"Version (\\d+\\.\\d+\\.\\d+)/(\\d+\\.\\d+\\.\\d+)"
        match = re.search(version_pattern, commit_message)

        if match:
            frontend_version = match.group(1)
            backend_version = match.group(2)

            # Restore version numbers
            version_service.set_versions_on_restore(frontend_version, backend_version)

        # Reset to target commit
        reset_result = subprocess.run(
            ["git", "reset", "--hard", target],
            capture_output=True,
            text=True,
            cwd=".."
        )

        if reset_result.returncode != 0:
            raise Exception(f"Git reset failed: {reset_result.stderr}")

        versions = version_service.get_versions()

        return {
            "message": f"Successfully rolled back to {target[:7]}",
            "frontend_version": versions["frontend_version"],
            "backend_version": versions["backend_version"]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to rollback: {str(e)}"
        )


@router.delete("/github/version/{version_hash}")'''

    pattern = r'@router\.post\("/github/rollback"\).*?(?=\n\n@router\.delete\("/github/version/\{version_hash\}"\))'

    if re.search(pattern, content, re.DOTALL):
        content = re.sub(pattern, new_function, content, flags=re.DOTALL)
        print("✓ 已替换rollback_version函数")
        return content, True
    else:
        print("⚠ 未找到rollback_version函数")
        return content, False

def replace_delete_function(content):
    """替换delete_version函数"""

    new_function = '''@router.delete("/github/version/{version_hash}")
async def delete_github_backup(
    version_hash: str,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, str]:
    """Delete a specific version backup from GitHub (delete tags)"""
    try:
        import subprocess

        # Check if commit exists
        check_result = subprocess.run(
            ["git", "cat-file", "-t", version_hash],
            capture_output=True,
            text=True,
            cwd=".."
        )

        if check_result.returncode != 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Version {version_hash[:7]} not found"
            )

        # Get commit message to find associated version
        log_result = subprocess.run(
            ["git", "log", "-1", "--pretty=format:%s", version_hash],
            capture_output=True,
            text=True,
            cwd=".."
        )

        commit_message = log_result.stdout.strip()

        # Extract version from commit message
        version_pattern = r"Version (\\d+\\.\\d+\\.\\d+)/(\\d+\\.\\d+\\.\\d+)"
        match = re.search(version_pattern, commit_message)

        if match:
            frontend_version = match.group(1)
            backend_version = match.group(2)

            # Delete tags if they exist
            for tag_name in [f"v{frontend_version}-frontend", f"v{backend_version}-backend"]:
                # Delete local tag
                subprocess.run(
                    ["git", "tag", "-d", tag_name],
                    capture_output=True,
                    text=True,
                    cwd=".."
                )

                # Delete remote tag
                subprocess.run(
                    ["git", "push", "origin", f":refs/tags/{tag_name}"],
                    capture_output=True,
                    text=True,
                    cwd=".."
                )

        return {
            "message": f"Successfully deleted backup tags for version {version_hash[:7]}",
            "note": "Commit history preserved for audit purposes. Tags removed from GitHub."
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete version backup: {str(e)}"
        )'''

    # 找到delete_version函数到下一个@router或文件结束
    pattern = r'@router\.delete\("/github/version/\{version_hash\}"\)\s*\nasync def delete_version\(.*?\n(?=\n@router\.|$)'

    if re.search(pattern, content, re.DOTALL):
        # 找到函数结束位置（下一个空行+@router或文件结束）
        match = re.search(r'(@router\.delete\("/github/version/\{version_hash\}"\).*?)((?=\n\n@router\.)|(?=\n\n\n@router\.)|$)', content, re.DOTALL)
        if match:
            old_func = match.group(1)
            content = content.replace(old_func, new_function)
            print("✓ 已替换delete_version函数")
            return content, True

    print("⚠ 未找到delete_version函数")
    return content, False

def main():
    print("=" * 70)
    print("系统版本管理模块 - 精确修改工具")
    print("=" * 70)
    print()

    system_py = Path("c:/app/hustle2026/backend/app/api/v1/system.py")

    if not system_py.exists():
        print(f"❌ 错误：找不到文件 {system_py}")
        return False

    # 备份文件
    backup_path = backup_file(system_py)

    # 读取文件
    content = read_file(system_py)

    # 应用修改
    success_count = 0

    print("\n开始应用修改...")
    print("-" * 70)

    content, success = replace_push_function(content)
    if success:
        success_count += 1

    content, success = replace_rollback_function(content)
    if success:
        success_count += 1

    content, success = replace_delete_function(content)
    if success:
        success_count += 1

    # 保存文件
    write_file(system_py, content)

    print("-" * 70)
    print(f"\n✓ 修改完成！成功修改 {success_count}/3 个函数")
    print(f"✓ 文件已保存: {system_py}")
    print(f"✓ 备份文件: {backup_path}")

    print("\n后续步骤：")
    print("1. 验证语法：cd backend && python -m py_compile app/api/v1/system.py")
    print("2. 重启后端服务")
    print("3. 测试功能")

    return True

if __name__ == "__main__":
    try:
        success = main()
        if not success:
            exit(1)
    except Exception as e:
        print(f"\n❌ 错误：{e}")
        import traceback
        traceback.print_exc()
        exit(1)
