"""Guards for MainWindow impairment mixin extraction."""
from __future__ import annotations

import ast
import os
import sys
import unittest

_TESTS = os.path.dirname(os.path.abspath(__file__))
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)
_ROOT = os.path.dirname(_TESTS)
_SRC = os.path.join(_ROOT, 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from _gui_source import load_main_window_source, method_src


class TestImpairmentExtraction(unittest.TestCase):
    def test_main_inherits_impairment_mixins(self) -> None:
        path = os.path.join(_SRC, 'gui', 'main.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        tree = ast.parse(src)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ZubCutApp')
        bases = []
        for b in cls.bases:
            if isinstance(b, ast.Name):
                bases.append(b.id)
            elif isinstance(b, ast.Attribute):
                bases.append(b.attr)
        for name in (
            'ImpairmentPlanMixin',
            'ImpairmentPrepMixin',
            'ImpairmentIcsGateMixin',
            'ImpairmentBlocksMixin',
            'ImpairmentLagMixin',
            'ImpairmentDupeMixin',
            'ImpairmentKillMixin',
            'ImpairmentPctCutMixin',
            'ImpairmentMitmMixin',
            'ImpairmentFlowNetMixin',
        ):
            self.assertIn(name, bases)

    def test_main_py_no_longer_defines_extracted_engines(self) -> None:
        path = os.path.join(_SRC, 'gui', 'main.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        for name in (
            'startLagSwitch',
            'stopDupe',
            'toggleKill',
            '_ensure_ics_lag_gate',
            '_prepare_victim_for_impairment',
            '_apply_victim_block',
        ):
            self.assertNotIn(f'def {name}(', src)

    def test_extracted_methods_still_resolvable(self) -> None:
        for name in (
            'startLagSwitch',
            'stopDupe',
            'toggleKill',
            '_ensure_ics_lag_gate',
            '_prepare_victim_for_impairment',
            '_apply_victim_block',
            '_set_countdown_label',
        ):
            body = method_src(name)
            self.assertIn(f'def {name}', body)

    def test_combined_source_still_large_enough(self) -> None:
        # Regression: extraction must not drop large engine bodies.
        src = load_main_window_source()
        self.assertGreater(len(src), 200_000)


if __name__ == '__main__':
    unittest.main()
