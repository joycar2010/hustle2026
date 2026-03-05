# ============================================
# rollback_version 函数完整替换代码
# 位置：system.py 第757-795行
# ============================================

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


# ============================================
# delete_github_backup 函数完整替换代码
# 位置：system.py 第798-825行
# 注意：函数名从 delete_version 改为 delete_github_backup
# ============================================

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
