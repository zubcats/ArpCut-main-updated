"""Defender exclusions: standalone Admin script plus best-effort setup hook."""
from __future__ import annotations

import os
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


class TestAllowZubCutDefender(unittest.TestCase):
    def test_setup_adds_install_dir_exclusion(self) -> None:
        iss_path = os.path.join(_ROOT, 'installer', 'ZubCut.iss')
        with open(iss_path, encoding='utf-8') as fh:
            iss = fh.read()
        self.assertIn('procedure AddDefenderExclusionForApp', iss)
        self.assertIn('Add-MpPreference -ExclusionPath', iss)
        self.assertIn('ExclusionProcess', iss)
        self.assertIn('AddDefenderExclusionForApp();', iss)
        post = iss[iss.index('if CurStep = ssPostInstall') :]
        self.assertLess(
            post.index('MaybeWriteClumsyBundleFlag'),
            post.index('AddDefenderExclusionForApp()'),
        )

    def test_script_excludes_install_dir_before_setup(self) -> None:
        ps1 = os.path.join(_ROOT, 'tools', 'Allow-ZubCut-Defender.ps1')
        bat = os.path.join(_ROOT, 'tools', 'Allow-ZubCut-Defender.bat')
        self.assertTrue(os.path.isfile(ps1))
        self.assertTrue(os.path.isfile(bat))
        with open(ps1, encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn('Add-MpPreference -ExclusionPath', src)
        self.assertIn('ExclusionProcess', src)
        self.assertIn('Program Files', src)
        self.assertIn('Downloads', src)
        self.assertIn('MpCmdRun.exe', src)
        with open(bat, encoding='utf-8') as fh:
            bat_src = fh.read()
        self.assertIn('RunAs', bat_src)
        self.assertIn('Allow-ZubCut-Defender.ps1', bat_src)


if __name__ == '__main__':
    unittest.main()
