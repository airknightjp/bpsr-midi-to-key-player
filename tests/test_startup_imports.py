from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StartupImportTests(unittest.TestCase):
    def test_main_import_defers_audio_engine_and_numpy(self) -> None:
        script = (
            "import sys; import main; "
            "print(int('software_synth' in sys.modules)); "
            "print(int('numpy' in sys.modules))"
        )
        env = os.environ.copy()
        dependency_path = str(ROOT / ".build_deps")
        existing_python_path = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(
            value for value in (dependency_path, existing_python_path) if value
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )

        self.assertEqual(result.stdout.splitlines(), ["0", "0"])


if __name__ == "__main__":
    unittest.main()
