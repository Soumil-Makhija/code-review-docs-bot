import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from reviewlens.gitdata import GitDataError, _changed_lines, _environment, _git, snapshot


class GitDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Synthetic Test")
        self.git("config", "user.email", "synthetic@example.invalid")
        self.write("sample.py", "first\nold\nlast\n")
        self.git("add", "--all")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD").strip()

    def git(self, *args):
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
        return subprocess.run(["git", *args], cwd=self.root, env=env, check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode() if isinstance(text, str) else text)

    def commit(self):
        self.git("add", "--all")
        self.git("commit", "-qm", "head")
        return self.git("rev-parse", "HEAD").strip()

    def test_exact_commits_changed_lines_and_worktree_independence(self):
        self.write("sample.py", "first\nnew\nlast\nextra\n")
        head = self.commit()
        self.write("sample.py", "PRIVATE UNCOMMITTED CONTENT\n")
        result = snapshot(self.root, self.base, "HEAD", ["sample.py"])
        self.assertEqual((result["base_commit"], result["head_commit"]), (self.base, head))
        file = result["files"][0]
        self.assertEqual(file["changed_base_lines"], [2])
        self.assertEqual(file["changed_head_lines"], [2, 4])
        self.assertEqual(file["head_text"], "first\nnew\nlast\nextra\n")
        self.assertIn("-old\n+new", result["diff"])
        self.assertNotIn("PRIVATE", str(result))
        self.assertNotIn(str(self.root), str(result))
        self.assertEqual(result, snapshot(self.root, self.base, head, ["sample.py"]))

    def test_added_deleted_and_sorted_paths(self):
        (self.root / "sample.py").unlink()
        self.write("added file.py", "new\nsecond")
        head = self.commit()
        files = snapshot(self.root, self.base, head, ["sample.py", "added file.py"])["files"]
        self.assertEqual([f["path"] for f in files], ["added file.py", "sample.py"])
        self.assertIsNone(files[0]["base_text"])
        self.assertEqual(files[0]["changed_head_lines"], [1, 2])
        self.assertIsNone(files[1]["head_text"])
        self.assertEqual(files[1]["changed_base_lines"], [1, 2, 3])

    def test_unicode_separators_are_not_git_line_breaks(self):
        self.write("sample.py", "first\u2028inside\nchanged\n")
        head = self.commit()
        result = snapshot(self.root, self.base, head, ["sample.py"])
        self.assertEqual(result["files"][0]["changed_head_lines"], [1, 2])

    def test_literal_metacharacter_path(self):
        self.write("literal[1].py", "old\n")
        base = self.commit()
        self.write("literal[1].py", "new\n")
        head = self.commit()
        self.assertEqual(snapshot(self.root, base, head, ["literal[1].py"])["files"][0]["path"], "literal[1].py")

    def test_invalid_selectors_rejected(self):
        for paths in ([], ["../sample.py"], ["/sample.py"], ["./sample.py"], ["a//b"],
                      [".git/config"], ["a/.GIT/config"], ["sample.py", "sample.py"],
                      ["a\\b"], ["a\nb"], ["x"] * 9, "sample.py"):
            with self.subTest(paths=paths), self.assertRaises(GitDataError):
                snapshot(self.root, self.base, "HEAD", paths)

    def test_unknown_unchanged_or_directory_selection_rejected(self):
        for paths in (["absent.py"], ["sample.py"], ["."]):
            with self.subTest(paths=paths), self.assertRaises(GitDataError):
                snapshot(self.root, self.base, "HEAD", paths)

    def test_bad_refs_do_not_become_git_options(self):
        for ref in ("--help", "missing", "", "HEAD\x00", True):
            with self.subTest(ref=ref), self.assertRaises(GitDataError):
                snapshot(self.root, ref, "HEAD", ["sample.py"])

    def test_binary_invalid_utf8_symlinks_rejected(self):
        for name, content in (("nul.txt", b"a\x00b"), ("invalid.txt", b"\xff")):
            self.write(name, content)
        (self.root / "link.py").symlink_to("sample.py")
        head = self.commit()
        for path in ("nul.txt", "invalid.txt", "link.py"):
            with self.subTest(path=path), self.assertRaises(GitDataError):
                snapshot(self.root, self.base, head, [path])

    def test_submodule_and_directory_entries_rejected(self):
        self.git("update-index", "--add", "--cacheinfo", "160000," + self.base + ",submodule")
        self.git("commit", "-qm", "gitlink")
        with self.assertRaises(GitDataError):
            snapshot(self.root, self.base, "HEAD", ["submodule"])
        self.write("folder/file.py", "new\n")
        head = self.commit()
        with self.assertRaises(GitDataError):
            snapshot(self.root, self.base, head, ["folder"])

    def test_oversized_blob_rejected_before_snapshot(self):
        self.write("sample.py", "x" * (20 * 1024))
        head = self.commit()
        with self.assertRaisesRegex(GitDataError, "20 KiB"):
            snapshot(self.root, self.base, head, ["sample.py"])

    def test_external_diff_and_worktree_attributes_do_not_execute(self):
        marker = self.root / "executed"
        self.git("config", "diff.external", "touch " + str(marker))
        self.git("config", "diff.evil.textconv", "touch " + str(marker))
        self.write("sample.py", "first\nnew\nlast\n")
        head = self.commit()
        self.write(".gitattributes", "*.py diff=evil\n")
        result = snapshot(self.root, self.base, head, ["sample.py"])
        self.assertEqual(result["files"][0]["changed_head_lines"], [2])
        self.assertFalse(marker.exists())

    def test_hunk_parser_rejects_inconsistent_counts(self):
        for patch in ("@@ -1,2 +1 @@\n-old\n+new\n", "@@ -1 +1 @@\n-old\n+new\n+extra\n", "@@ broken\n", "@@ -0 +1 @@\n-old\n+new\n"):
            with self.subTest(patch=patch), self.assertRaises(GitDataError):
                _changed_lines(patch)

    def test_local_diff_configuration_cannot_change_patch_format(self):
        self.write("sample.py", "first\nnew\nlast\n")
        head = self.commit()
        expected = snapshot(self.root, self.base, head, ["sample.py"])
        self.git("config", "diff.orderFile", str(self.root / "absent-order-file"))
        self.git("config", "diff.outputIndicatorNew", "!")
        self.git("config", "diff.outputIndicatorOld", "?")
        self.assertEqual(snapshot(self.root, self.base, head, ["sample.py"]), expected)

    def test_hunk_parser_excludes_context(self):
        self.assertEqual(_changed_lines("@@ -2,3 +2,3 @@\n context\n-old\n+new\n end\n"), ([3], [3]))

    def test_streaming_output_cap_and_lazy_fetch_disabled(self):
        with patch("reviewlens.gitdata.MAX_OUTPUT_BYTES", 5), self.assertRaisesRegex(GitDataError, "output exceeds"):
            _git(self.root, "--version")
        self.assertEqual(_environment()["GIT_NO_LAZY_FETCH"], "1")


if __name__ == "__main__":
    unittest.main()
