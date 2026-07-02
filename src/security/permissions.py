"""Permission enforcement for all agent tool calls."""

from pathlib import Path
from typing import Any
import yaml


class PermissionError(Exception):
    pass


class PermissionGuard:
    """Enforces path, command, and size limits from config."""

    def __init__(self, config: dict):
        sec = config.get("security", {})
        self.allowed_paths = [Path(p) for p in sec.get("allowed_paths", [])]
        self.blocked_paths = [Path(p) for p in sec.get("blocked_paths", [])]
        self.allowed_commands = set(sec.get("allowed_commands", []))
        self.require_approval = sec.get("require_approval_for", [])
        self.max_file_mb = sec.get("max_file_size_mb", 100)
        self.max_exec_sec = sec.get("max_execution_time_sec", 30)

    def check_path(self, path: str, operation: str = "read") -> None:
        p = Path(path).resolve()
        for blocked in self.blocked_paths:
            try:
                p.relative_to(blocked.resolve())
                raise PermissionError(
                    f"Path '{path}' is in blocked zone '{blocked}'"
                )
            except ValueError:
                pass

        if operation == "write" and self.allowed_paths:
            allowed = any(
                self._is_under(p, a) for a in self.allowed_paths
            )
            if not allowed:
                raise PermissionError(
                    f"Write to '{path}' outside allowed paths"
                )

    def check_command(self, command: str) -> None:
        base = command.strip().split()[0] if command.strip() else ""
        for danger in self.require_approval:
            if danger.lower() in command.lower():
                raise PermissionError(
                    f"Command '{base}' contains restricted keyword '{danger}' — manual approval required"
                )

    def check_file_size(self, size_bytes: int) -> None:
        if size_bytes > self.max_file_mb * 1024 * 1024:
            raise PermissionError(
                f"File size {size_bytes/1024/1024:.1f} MB exceeds limit {self.max_file_mb} MB"
            )

    def _is_under(self, path: Path, parent: Path) -> bool:
        try:
            path.relative_to(parent.resolve())
            return True
        except ValueError:
            return False


REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def load_guard(config_path: str | None = None) -> PermissionGuard:
    path = Path(config_path) if config_path else REPO_ROOT / "config.yaml"
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return PermissionGuard(cfg)
