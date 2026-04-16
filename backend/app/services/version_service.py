"""Version management service"""
from pathlib import Path
import json
from typing import Dict
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class VersionService:
    """Manage system version numbers"""

    def __init__(self):
        self.version_file = Path(__file__).parent.parent.parent / "version.json"
        self._ensure_version_file()

    def _ensure_version_file(self):
        """Ensure version file exists with default values"""
        if not self.version_file.exists():
            default_version = {
                "frontend_version": "1.0.0",
                "backend_version": "1.0.0",
                "last_backup_time": None,
                "last_restore_time": None
            }
            self._save_version(default_version)
            logger.info(f"Created version file at {self.version_file}")

    def _load_version(self) -> Dict:
        """Load version data from file"""
        try:
            with open(self.version_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading version file: {e}")
            return {
                "frontend_version": "1.0.0",
                "backend_version": "1.0.0",
                "last_backup_time": None,
                "last_restore_time": None
            }

    def _save_version(self, data: Dict):
        """Save version data to file"""
        try:
            with open(self.version_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved version data: {data}")
        except Exception as e:
            logger.error(f"Error saving version file: {e}")
            raise

    def _increment_version(self, version: str) -> str:
        """Increment patch version (X.Y.Z -> X.Y.Z+1)

        Args:
            version: Version string in format X.Y.Z

        Returns:
            Incremented version string

        Raises:
            ValueError: If version format is invalid
        """
        try:
            parts = version.split('.')
            if len(parts) != 3:
                raise ValueError(f"Invalid version format: {version}")

            major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
            patch += 1

            new_version = f"{major}.{minor}.{patch}"
            logger.info(f"Incremented version from {version} to {new_version}")
            return new_version
        except Exception as e:
            raise ValueError(f"Failed to increment version {version}: {e}")

    def get_versions(self) -> Dict:
        """Get current version numbers

        Returns:
            Dictionary containing version information
        """
        return self._load_version()

    def increment_on_backup(self) -> Dict:
        """Increment both frontend and backend versions on backup

        Returns:
            Updated version data
        """
        data = self._load_version()

        # Increment versions
        old_frontend = data["frontend_version"]
        old_backend = data["backend_version"]

        data["frontend_version"] = self._increment_version(data["frontend_version"])
        data["backend_version"] = self._increment_version(data["backend_version"])
        data["last_backup_time"] = datetime.utcnow().isoformat() + "Z"

        self._save_version(data)

        logger.info(
            f"Backup version increment: "
            f"Frontend {old_frontend} -> {data['frontend_version']}, "
            f"Backend {old_backend} -> {data['backend_version']}"
        )

        return data

    def set_versions_on_restore(self, frontend_version: str, backend_version: str) -> Dict:
        """Set specific versions on restore

        Args:
            frontend_version: Target frontend version
            backend_version: Target backend version

        Returns:
            Updated version data

        Raises:
            ValueError: If version format is invalid
        """
        # Validate version format
        for version in [frontend_version, backend_version]:
            parts = version.split('.')
            if len(parts) != 3 or not all(p.isdigit() for p in parts):
                raise ValueError(f"Invalid version format: {version}. Must be X.Y.Z")

        data = self._load_version()
        data["frontend_version"] = frontend_version
        data["backend_version"] = backend_version
        data["last_restore_time"] = datetime.utcnow().isoformat() + "Z"

        self._save_version(data)

        logger.info(
            f"Restore version set: "
            f"Frontend -> {frontend_version}, "
            f"Backend -> {backend_version}"
        )

        return data


# Global instance
version_service = VersionService()
