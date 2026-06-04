"""Immutable audit logging for all agent actions."""

import json
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AuditLogger:
    """Append-only audit log with chained hash for tamper detection."""

    def __init__(self, log_path: str = "./logs/audit.jsonl"):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._prev_hash = self._read_last_hash()

    def _read_last_hash(self) -> str:
        if not self.log_path.exists():
            return "GENESIS"
        with open(self.log_path, "rb") as f:
            lines = f.read().splitlines()
        if not lines:
            return "GENESIS"
        try:
            last = json.loads(lines[-1])
            return last.get("hash", "GENESIS")
        except Exception:
            return "GENESIS"

    def _hash_entry(self, entry: dict) -> str:
        payload = json.dumps(entry, sort_keys=True).encode()
        return hashlib.sha256(payload).hexdigest()

    def log(self, event_type: str, actor: str, action: str,
            target: str = "", result: str = "", metadata: dict | None = None) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "actor": actor,
            "action": action,
            "target": target,
            "result": result,
            "metadata": metadata or {},
            "prev_hash": self._prev_hash,
        }
        entry["hash"] = self._hash_entry(entry)
        self._prev_hash = entry["hash"]

        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def verify_chain(self) -> tuple[bool, str]:
        if not self.log_path.exists():
            return True, "Empty log"
        entries = []
        with open(self.log_path, encoding="utf-8") as f:
            for i, line in enumerate(f):
                try:
                    entries.append((i + 1, json.loads(line.strip())))
                except json.JSONDecodeError as e:
                    return False, f"Line {i+1}: JSON parse error: {e}"

        prev = "GENESIS"
        for line_num, entry in entries:
            expected = entry.get("hash")
            stored_prev = entry.get("prev_hash")
            if stored_prev != prev:
                return False, f"Line {line_num}: chain broken (prev_hash mismatch)"
            check = {k: v for k, v in entry.items() if k != "hash"}
            computed = hashlib.sha256(
                json.dumps(check, sort_keys=True).encode()
            ).hexdigest()
            if computed != expected:
                return False, f"Line {line_num}: hash mismatch (tampered?)"
            prev = expected

        return True, f"Chain valid ({len(entries)} entries)"


_audit: AuditLogger | None = None


def get_audit(log_path: str = "./logs/audit.jsonl") -> AuditLogger:
    global _audit
    if _audit is None:
        _audit = AuditLogger(log_path)
    return _audit
