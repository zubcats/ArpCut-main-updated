"""Retrying rolling GitHub Release publish used by the installer workflow."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPT = os.path.join(_ROOT, "tools", "ci_publish_github_release.py")
mod = SourceFileLoader("ci_publish_github_release", _SCRIPT).load_module()


def _gh(returncode: int, stdout: str = "", stderr: str = "") -> mod.GhResult:
    return mod.GhResult(returncode=returncode, stdout=stdout, stderr=stderr)


class _ScriptedRunner:
    def __init__(self, responses: list[mod.GhResult]) -> None:
        self.responses = list(responses)
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> mod.GhResult:
        self.calls.append(list(args))
        if not self.responses:
            raise AssertionError(f"unexpected gh call: {args}")
        return self.responses.pop(0)


class TestCiPublishGithubRelease(unittest.TestCase):
    def test_edits_existing_release_and_uploads(self) -> None:
        runner = _ScriptedRunner(
            [
                _gh(0, stdout="ZubCut (experimental)"),
                _gh(0),
                _gh(0),
                _gh(0),
            ]
        )
        with tempfile.TemporaryDirectory() as td:
            installer = Path(td) / "ZubCut-Setup-experimental.exe"
            info = Path(td) / "build-info.json"
            installer.write_bytes(b"exe")
            info.write_text("{}", encoding="utf-8")
            mod.publish_once(
                runner,
                tag="experimental-latest",
                title="ZubCut (experimental)",
                target="abc123",
                prerelease=True,
                files=[installer, info],
            )
        self.assertEqual(runner.calls[0][:3], ["gh", "release", "view"])
        self.assertEqual(runner.calls[1][:3], ["gh", "release", "edit"])
        self.assertIn("--prerelease", runner.calls[1])
        self.assertIn("--latest=false", runner.calls[1])
        self.assertIn("--notes-file", runner.calls[1])
        self.assertEqual(runner.calls[2][:3], ["gh", "release", "upload"])
        self.assertIn("--clobber", runner.calls[2])
        self.assertTrue(any(str(c).endswith(".exe") for c in runner.calls[2]))
        self.assertFalse(any(str(c).endswith("build-info.json") for c in runner.calls[2]))
        self.assertEqual(runner.calls[3][:3], ["gh", "release", "delete-asset"])

    def test_creates_release_when_missing(self) -> None:
        runner = _ScriptedRunner(
            [
                _gh(1, stderr="release not found"),
                _gh(0, stdout="https://github.com/example/releases/tag/stable-latest"),
                _gh(0),
            ]
        )
        with tempfile.TemporaryDirectory() as td:
            installer = Path(td) / "ZubCut-Setup.exe"
            installer.write_bytes(b"exe")
            mod.publish_once(
                runner,
                tag="stable-latest",
                title="ZubCut",
                target="def456",
                prerelease=False,
                files=[installer],
            )
        self.assertEqual(runner.calls[1][:3], ["gh", "release", "create"])
        self.assertNotIn("--prerelease", runner.calls[1])
        self.assertIn("--latest=false", runner.calls[1])

    def test_retries_transient_view_error(self) -> None:
        sleeps: list[float] = []
        runner = _ScriptedRunner(
            [
                _gh(1, stderr="No server is currently available to service your request."),
                _gh(0, stdout="ZubCut"),
                _gh(0),
                _gh(0),
                _gh(0),
            ]
        )
        with tempfile.TemporaryDirectory() as td:
            installer = Path(td) / "ZubCut-Setup.exe"
            installer.write_bytes(b"exe")
            mod.publish_with_retries(
                tag="stable-latest",
                title="ZubCut",
                target="sha",
                prerelease=False,
                files=[installer],
                attempts=3,
                initial_sleep_s=2.0,
                max_sleep_s=10.0,
                runner=runner,
                sleeper=sleeps.append,
            )
        self.assertEqual(sleeps, [2.0])
        self.assertEqual(len(runner.calls), 5)

    def test_missing_file_fails_before_gh(self) -> None:
        runner = _ScriptedRunner([])
        with self.assertRaises(mod.PublishError) as ctx:
            mod.publish_with_retries(
                tag="stable-latest",
                title="ZubCut",
                target="sha",
                prerelease=False,
                files=[Path("output/missing.exe")],
                runner=runner,
            )
        self.assertIn("Missing release file", str(ctx.exception))
        self.assertEqual(runner.calls, [])

    def test_workflow_uses_retry_script_instead_of_softprops(self) -> None:
        text = (
            Path(_ROOT) / ".github" / "workflows" / "build-windows-installer.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("tools/ci_publish_github_release.py", text)
        self.assertIn("publish-experimental", text)
        self.assertIn("publish-stable", text)
        self.assertNotIn("softprops/action-gh-release", text)
        self.assertIn("--notes-file output/build-info.json", text)
        self.assertNotIn("--file output/build-info.json", text)


if __name__ == "__main__":
    unittest.main()
