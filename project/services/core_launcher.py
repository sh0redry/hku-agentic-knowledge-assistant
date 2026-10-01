"""Publish the local installation path for the Desktop's fixed Core launcher."""
import json
import os
import sys
import tempfile
from pathlib import Path


def publish_launcher(root: Path, *, path: Path | None = None) -> bool:
    if path is None:
        profile = os.environ.get("USERPROFILE")
        if sys.platform != "win32" or not profile:
            return False
        path = Path(profile) / ".hku-agents" / "core-launch-v1.json"
    root = root.resolve(strict=True)
    if not (root / "project" / "app.py").is_file() or not (root / ".venv" / "Scripts" / "pythonw.exe").is_file():
        raise ValueError("Local Core installation is incomplete")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Invalid launcher registration")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump({"version": 1, "root": str(root)}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return True
