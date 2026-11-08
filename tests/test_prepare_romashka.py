import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/prepare_romashka.py'


class ExportTests(unittest.TestCase):
    def run_export(self, dest):
        return subprocess.run([sys.executable, str(SCRIPT), '--destination', str(dest), '--no-git'],
                              capture_output=True, text=True)

    def test_export_is_runnable_without_private_materials(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'shop'
            result = self.run_export(dest)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests'],
                                    cwd=dest, capture_output=True, text=True, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((dest / 'data').exists())
            self.assertFalse((dest / '.env').exists())
            self.assertFalse((dest / 'acceptance').exists())
            self.assertFalse(list(dest.rglob('*.pyc')))

    def test_existing_directory_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'shop'
            dest.mkdir()
            marker = dest / 'my-work.txt'
            marker.write_text('keep me')
            result = self.run_export(dest)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('already exists', result.stderr)
            self.assertEqual(marker.read_text(), 'keep me')
            self.assertEqual(sorted(p.name for p in dest.iterdir()), ['my-work.txt'])


if __name__ == '__main__':
    unittest.main()
