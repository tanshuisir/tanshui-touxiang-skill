"""Verify that public installs resolve dependencies without machine-specific paths."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
PROBE = '''
import json
import sys
sys.path.insert(0, sys.argv[1])
import build_prompt
import run_avatar
print(json.dumps({'gateway': str(build_prompt.GEN_IMG),
                  'installed': str(run_avatar.INSTALLED_SKILL)}))
'''


class PortablePathTests(unittest.TestCase):
    def probe(self, **overrides):
        environment = dict(os.environ)
        environment.pop('CODEX_HOME', None)
        environment.pop('GEN_IMG_SKILL_DIR', None)
        environment.update(overrides)
        result = subprocess.run([sys.executable, '-c', PROBE, str(SCRIPTS)],
                                env=environment, check=True, capture_output=True, text=True)
        return json.loads(result.stdout)

    def test_default_uses_current_user_home(self):
        result = self.probe()
        home = Path.home() / '.codex' / 'skills'
        self.assertEqual(result['gateway'], str(home / 'gen-img/scripts/run.py'))
        self.assertEqual(result['installed'], str(home / 'tanshui-touxiang-skill'))

    def test_custom_codex_home(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.probe(CODEX_HOME=directory)
            self.assertEqual(result['gateway'], str(Path(directory) / 'skills/gen-img/scripts/run.py'))
            self.assertEqual(result['installed'], str(Path(directory) / 'skills/tanshui-touxiang-skill'))

    def test_gateway_directory_override(self):
        with tempfile.TemporaryDirectory() as directory:
            dependency = Path(directory) / 'custom image skill'
            result = self.probe(CODEX_HOME=directory, GEN_IMG_SKILL_DIR=str(dependency))
            self.assertEqual(result['gateway'], str(dependency / 'scripts/run.py'))
            self.assertEqual(result['installed'], str(Path(directory) / 'skills/tanshui-touxiang-skill'))


if __name__ == '__main__':
    unittest.main()
