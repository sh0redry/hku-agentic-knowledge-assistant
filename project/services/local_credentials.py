"""Current-user protected credentials shared by Core and the Desktop Host."""
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from services.data_protection import WindowsUserDataProtector


class LocalCredentialError(RuntimeError):
    pass


def credential_path() -> Path | None:
    # Store-installed Python redirects AppData writes into its package sandbox.
    # A user-profile directory is shared consistently with the Desktop Node Host.
    profile = os.environ.get("USERPROFILE")
    return Path(profile) / ".hku-agents" / "connection-v1.json" if sys.platform == "win32" and profile else None


def _origin(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise LocalCredentialError("Automatic connection requires a loopback service origin.")
    return value.rstrip("/")


def load_tokens(base_url: str, *, path: Path | None = None, protector=None) -> dict[str, str]:
    target = path if path is not None else credential_path()
    if path is None and target is not None and not target.exists() and os.environ.get("LOCALAPPDATA"):
        legacy = Path(os.environ["LOCALAPPDATA"]) / "HKU AGENTS" / "connection-v1.json"
        if legacy.exists():
            target = legacy
    if target is None or not target.exists():
        return {}
    try:
        if target.is_symlink() or target.stat().st_size > 16384:
            raise ValueError("Invalid credential file")
        saved = json.loads(target.read_text(encoding="utf-8"))
        if saved.get("version") != 1:
            raise ValueError("Invalid credential version")
        guard = protector or WindowsUserDataProtector()
        integration = json.loads(guard.unprotect(base64.b64decode(saved["integration"], validate=True)))
        if integration["base_url"] != _origin(base_url):
            return {}
        pairing = guard.unprotect(base64.b64decode(saved["browser_pairing"], validate=True)).decode("utf-8")
        token = integration["token"]
        if not isinstance(token, str) or not 32 <= len(token) <= 200 or not 32 <= len(pairing) <= 200:
            raise ValueError("Invalid credential length")
        return {"integration": token, "browser_pairing": pairing}
    except Exception as exc:
        raise LocalCredentialError("The protected local connection could not be read.") from exc


def publish_tokens(base_url: str, integration: str, pairing: str, *, path: Path | None = None, protector=None) -> bool:
    target = path if path is not None else credential_path()
    if target is None:
        return False
    try:
        origin = _origin(base_url)
        if not 32 <= len(integration) <= 200 or not 32 <= len(pairing) <= 200:
            raise ValueError("Invalid credentials")
        guard = protector or WindowsUserDataProtector()
        saved = {"version": 1,
                 "integration": base64.b64encode(guard.protect(json.dumps({"base_url": origin, "token": integration}).encode("utf-8"))).decode("ascii"),
                 "browser_pairing": base64.b64encode(guard.protect(pairing.encode("utf-8"))).decode("ascii")}
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(saved, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        return True
    except Exception as exc:
        raise LocalCredentialError("The local connection could not be protected for this Windows user.") from exc
