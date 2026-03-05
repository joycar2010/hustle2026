# 系统版本管理模块修复说明

## 已完成的修改

### 1. 创建版本号管理服务
✅ 文件：`backend/app/services/version_service.py`
- 实现版本号自动增减逻辑
- 备份时版本号+0.0.1
- 还原时回退到指定版本号
- 版本号存储在`backend/version.json`

### 2. 更新system.py导入
✅ 在`backend/app/api/v1/system.py`顶部添加：
```python
import re
from app.services.version_service import version_service
```

### 3. 更新get_system_info函数
✅ 已修改`backend/app/api/v1/system.py`的`get_system_info`函数
- 从version_service读取当前版本号
- 不再使用硬编码的"1.0.0"

## 需要手动修改的部分

由于文件较大，以下函数需要手动替换：

### 4. 修改push_to_github函数（第592-754行）

**位置**：`backend/app/api/v1/system.py` 第592行开始

**需要修改的关键点**：

1. 在有变更时，先调用`version_service.increment_on_backup()`增加版本号
2. 提交消息格式改为：`Version X.Y.Z/A.B.C: 备注`
3. 添加详细的错误处理（认证失败、分支冲突、API限流）
4. 返回值中包含新的版本号

**修改后的函数**（替换第592-754行）：

```python
@router.post("/github/push")
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
                    "分支冲突：请先拉取最新代码并解决冲突。\n"
                    "建议操作：\n"
                    "1. 在本地执行 git pull origin " + current_branch + "\n"
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
                    "GitHub 认证失败：\n"
                    "1. 检查 GitHub Personal Access Token 是否有效\n"
                    "2. 确认 token 具有 'repo' 权限\n"
                    "3. 验证 Git 配置中的凭据是否正确"
                )
            elif "rate limit" in error_msg:
                raise Exception(
                    "GitHub API 限流：\n"
                    "请稍后再试，或检查 API 调用频率"
                )
            elif "rejected" in error_msg:
                raise Exception(
                    "推送被拒绝：\n"
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
```

### 5. 修改rollback_version函数（第757-794行）

**位置**：`backend/app/api/v1/system.py` 第757行开始

**需要修改的关键点**：

1. 从提交消息中提取版本号
2. 调用`version_service.set_versions_on_restore()`设置版本号
3. 返回值中包含版本号信息

**修改后的函数**（替换第757-794行）：

```python
@router.post("/github/rollback")
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
        version_pattern = r"Version (\d+\.\d+\.\d+)/(\d+\.\d+\.\d+)"
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
```

### 6. 修改delete_version函数（第798-825行）

**位置**：`backend/app/api/v1/system.py` 第798行开始

**当前问题**：执行的是`git revert`（还原提交），应该改为删除GitHub备份（删除tag）

**修改后的函数**（替换第798-825行）：

```python
@router.delete("/github/version/{version_hash}")
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
        version_pattern = r"Version (\d+\.\d+\.\d+)/(\d+\.\d+\.\d+)"
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
        )
```

## 前端修改

前端修改较为复杂，建议创建新的修复版本。主要修改点：

1. 使用Element Plus的MessageBox和Message组件
2. 添加Loading状态
3. 更新pushToGitHub函数显示版本号
4. 更新rollbackToVersion函数显示版本号
5. 修改deleteVersionByHash函数的确认提示和功能说明

详细的前端修改代码请参考之前提供的完整方案。

## 部署步骤

1. 确认`backend/app/services/version_service.py`已创建
2. 手动修改`backend/app/api/v1/system.py`的三个函数
3. 重启后端服务
4. 修改前端System.vue
5. 重新构建前端
6. 测试功能

## 测试验证

1. 测试版本号增减：备份后版本号+0.0.1
2. 测试版本号还原：还原到指定版本后版本号回退
3. 测试GitHub推送错误提示
4. 测试删除按钮功能（删除tag而不是revert）
