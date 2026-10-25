"""Offline first-install and preservation checks; no production state touched."""
import hashlib
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / 'scripts'))
import manage
import prepare


class PreparationTests(unittest.TestCase):
    def test_first_install_preservation_and_integrity(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'project with spaces'
            home = Path(folder) / 'home'
            root.mkdir()
            for name in ('memory.env.example', 'tasks.env.example'):
                shutil.copy2(SOURCE / name, root / name)
            model = home / '.cache/mcp_memory/onnx_models' / prepare.MODEL
            model.mkdir(parents=True)
            (model / 'config.json').write_bytes(b'test model')
            digest = hashlib.sha256(b'test model').hexdigest()
            (root / 'model.sha256').write_text(f'{digest}  config.json\n')
            with patch.object(prepare, 'ROOT', root), patch.object(manage, 'ROOT', root), \
                 patch.object(Path, 'home', return_value=home), \
                 patch.object(shutil, 'which', return_value='/test node/bin/node'), \
                 patch.object(sys, 'argv', ['prepare.py']):
                prepare.main()
                self.assertEqual(manage.envfile('tasks.env')['AGENT_TASKS_DB'],
                                 str(root / 'agent-tasks/data/agent-tasks.db'))
                self.assertEqual(manage.envfile('tasks.env')['TASKS_NODE'], '/test node/bin/node')
                private = [root / name for name in ('memory.env', 'tasks.env', 'runtime/api-key')]
                before = [path.read_bytes() for path in private]
                self.assertTrue(all(path.stat().st_mode & 0o077 == 0 for path in private))
                prepare.main()
                self.assertEqual(before, [path.read_bytes() for path in private])
                # A fresh install must back up config even without databases or clients.
                with patch.object(manage, 'RUNTIME', root / 'runtime'):
                    snapshot = manage.backup()
                self.assertTrue((snapshot / 'manifest.json').exists())
                (model / 'config.json').write_bytes(b'changed')
                with self.assertRaisesRegex(SystemExit, 'checksum mismatch'):
                    prepare.main()
                self.assertEqual((model / 'config.json').read_bytes(), b'changed')
                self.assertEqual(before, [path.read_bytes() for path in private])


if __name__ == '__main__':
    unittest.main()
