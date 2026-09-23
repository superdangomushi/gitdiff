"""The original script path must still work from another working directory."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "gitdiff.py"


class CliTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = directory.name
        self.env = os.environ.copy()
        # Avoid discovering a repository above the temporary directory.
        self.env["GIT_CEILING_DIRECTORIES"] = str(Path(directory.name).resolve().parent)
        self.env.pop("GIT_DIR", None)
        self.env.pop("GIT_WORK_TREE", None)

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-B", str(SCRIPT), *args],
            cwd=self.directory, env=self.env, capture_output=True, text=True,
        )

    def test_help_outside_repository(self):
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("branch-a [branch-b]", result.stdout)

    def test_non_repository_error(self):
        result = self.run_cli("main")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("not inside a git repository", result.stdout)

    def test_invalid_ref_error(self):
        subprocess.run(
            ["git", "init", "--quiet", self.directory],
            env=self.env, check=True, capture_output=True,
        )
        result = self.run_cli("missing-ref")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("'missing-ref' is not a valid branch or ref", result.stdout)
