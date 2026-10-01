import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))
from services.core_launcher import publish_launcher


class CoreLauncherTests(unittest.TestCase):
    def test_publish_fixed_installation_and_refuse_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "registration.json"
            with self.assertRaises(ValueError):
                publish_launcher(root, path=target)
            self.assertFalse(target.exists())
            (root / "project").mkdir()
            (root / "project" / "app.py").write_text("# fixture", encoding="utf-8")
            (root / ".venv" / "Scripts").mkdir(parents=True)
            (root / ".venv" / "Scripts" / "pythonw.exe").write_text("fixture", encoding="utf-8")
            self.assertTrue(publish_launcher(root, path=target))
            self.assertEqual(json.loads(target.read_text()), {"version": 1, "root": str(root.resolve())})


if __name__ == "__main__":
    unittest.main()
