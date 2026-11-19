"""Read selected committed UTF-8 files and exact Git changed-line evidence."""

from __future__ import annotations

import os
from pathlib import Path
import re
import selectors
import subprocess
import time

MAX_SOURCE_BYTES = 20 * 1024
MAX_PATHS = 8
MAX_OUTPUT_BYTES = 256 * 1024
_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_HUNK = re.compile(r"@@ -([0-9]+)(?:,([0-9]+))? \+([0-9]+)(?:,([0-9]+))? @@(?: .*)?\Z")


class GitDataError(ValueError):
    """The selected committed evidence cannot be read safely or unambiguously."""


def _environment():
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_ATTR_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
                "GIT_NO_REPLACE_OBJECTS": "1", "GIT_OPTIONAL_LOCKS": "0",
                "GIT_NO_LAZY_FETCH": "1",
                "LC_ALL": "C", "LANG": "C"})
    return env


def _git(repo, *args, gitdir=None):
    command = ["git", "--no-pager", "--literal-pathspecs",
               "-c", "core.fsmonitor=false", "-c", "core.hooksPath=" + os.devnull,
               "-c", "core.attributesFile=" + os.devnull, "-c", "color.ui=false",
               "-c", "diff.external=", "-c", "diff.relative=false",
               "-c", "diff.orderFile=" + os.devnull]
    if gitdir is not None:
        # A bare view prevents committed comparisons consulting worktree files.
        command.extend(["--git-dir=" + gitdir, "--bare"])
    process = None
    output = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + 10
    try:
        process = subprocess.Popen(command + list(args), cwd=repo, env=_environment(),
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, 10)
                for key, _ in selector.select(remaining):
                    chunk = os.read(key.fd, 65_536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    output[key.data].extend(chunk)
                    if len(output[key.data]) > MAX_OUTPUT_BYTES:
                        raise GitDataError("Git output exceeds the 256 KiB limit")
        process.wait(timeout=max(0.001, deadline - time.monotonic()))
    except (OSError, subprocess.TimeoutExpired, GitDataError) as error:
        if process is not None:
            process.kill()
            process.wait()
        if isinstance(error, GitDataError):
            raise
        raise GitDataError("Git is unavailable or exceeded its 10-second command limit") from error
    finally:
        if process is not None:
            process.stdout.close()
            process.stderr.close()
    if process.returncode:
        raise GitDataError("Git could not read the selected repository or committed revision")
    return bytes(output["stdout"])


def _selectors(paths):
    if type(paths) not in {list, tuple} or not 1 <= len(paths) <= MAX_PATHS:
        raise GitDataError("Select between 1 and 8 explicit file paths")
    for path in paths:
        if (type(path) is not str or not path or len(path.encode("utf-8")) > 2048
                or "\\" in path or any(ord(char) < 32 or ord(char) == 127 for char in path)
                or any(part in {"", ".", ".."} or part.casefold() == ".git" for part in path.split("/"))):
            raise GitDataError("Paths must be explicit relative file names without traversal or .git components")
    if len(set(paths)) != len(paths):
        raise GitDataError("Selected paths must be unique")
    return sorted(paths)


def _commit(repo, gitdir, revision):
    if type(revision) is not str or not revision or len(revision) > 200 or "\x00" in revision:
        raise GitDataError("A revision must be a nonempty bounded string")
    raw = _git(repo, "rev-parse", "--verify", "--end-of-options", revision + "^{commit}", gitdir=gitdir)
    value = raw.decode("ascii", errors="strict").strip()
    if not _OID.fullmatch(value):
        raise GitDataError("Git did not resolve an exact commit object ID")
    return value


def _entry(repo, gitdir, commit, path):
    raw = _git(repo, "ls-tree", "-z", commit, "--", path, gitdir=gitdir)
    if not raw:
        return None
    records = raw.split(b"\x00")
    if len(records) != 2 or records[-1] != b"":
        raise GitDataError("A selected path must identify exactly one file")
    try:
        metadata, name = records[0].split(b"\t", 1)
        mode, kind, oid = metadata.decode("ascii").split(" ")
    except (ValueError, UnicodeError) as error:
        raise GitDataError("Malformed Git tree entry") from error
    if name != path.encode("utf-8") or mode not in {"100644", "100755"} or kind != "blob" or not _OID.fullmatch(oid):
        raise GitDataError("Selected paths must be regular tracked files; symlinks, directories and submodules are unsupported")
    return oid


def _changed_lines(patch):
    """Parse actual +/- lines and verify every unified hunk's declared counts."""
    old_lines, new_lines = set(), set()
    active = False
    old = new = old_end = new_end = 0
    for line in patch.split("\n"):
        if line.startswith("@@"):
            if active and (old != old_end or new != new_end):
                raise GitDataError("Git hunk line counts do not match")
            match = _HUNK.fullmatch(line)
            if not match:
                raise GitDataError("Malformed Git hunk header")
            old, old_count, new, new_count = match.groups()
            old, new = int(old), int(new)
            old_count = 1 if old_count is None else int(old_count)
            new_count = 1 if new_count is None else int(new_count)
            if (old_count and old < 1) or (new_count and new < 1):
                raise GitDataError("Invalid Git hunk line numbers")
            old_end, new_end = old + old_count, new + new_count
            active = True
        elif active:
            if line == "\\ No newline at end of file":
                continue
            if not line and old == old_end and new == new_end:
                continue
            if line.startswith("-"):
                old_lines.add(old)
                old += 1
            elif line.startswith("+"):
                new_lines.add(new)
                new += 1
            elif line.startswith(" "):
                old += 1
                new += 1
            else:
                raise GitDataError("Unexpected line inside Git hunk")
            if old > old_end or new > new_end:
                raise GitDataError("Git hunk contains more lines than declared")
    if active and (old != old_end or new != new_end):
        raise GitDataError("Git hunk line counts do not match")
    return sorted(old_lines), sorted(new_lines)


def _diff(repo, gitdir, base, head, path, context):
    return _git(repo, "diff", "--no-ext-diff", "--no-textconv", "--no-color",
                "--no-renames", "--text", "--diff-algorithm=myers", "--no-indent-heuristic",
                "--output-indicator-new=+", "--output-indicator-old=-", "--output-indicator-context= ",
                "--inter-hunk-context=0", "--src-prefix=a/", "--dst-prefix=b/",
                f"--unified={context}", base, head, "--", path, gitdir=gitdir).decode("utf-8", errors="strict")


def snapshot(repo, base, head, paths):
    """Snapshot only explicitly selected committed text; never read a remote."""
    paths = _selectors(paths)
    repo = Path(repo)
    if not repo.is_dir():
        raise GitDataError("The selected repository directory does not exist")
    gitdir = os.fsdecode(_git(repo, "rev-parse", "--absolute-git-dir").rstrip(b"\n"))
    base_commit = _commit(repo, gitdir, base)
    head_commit = _commit(repo, gitdir, head)
    entries = [(path, _entry(repo, gitdir, base_commit, path), _entry(repo, gitdir, head_commit, path)) for path in paths]
    sizes = {}
    for _, old_oid, new_oid in entries:
        for oid in (old_oid, new_oid):
            if oid is not None and oid not in sizes:
                raw = _git(repo, "cat-file", "-s", oid, gitdir=gitdir).strip()
                if not raw.isdigit():
                    raise GitDataError("Git returned an invalid blob size")
                sizes[oid] = int(raw)
    if sum(sizes.get(oid, 0) for _, old_oid, new_oid in entries for oid in (old_oid, new_oid)) > MAX_SOURCE_BYTES:
        raise GitDataError("Selected base and head source exceeds the combined 20 KiB limit")
    texts = {}
    for oid in sizes:
        raw = _git(repo, "cat-file", "blob", oid, gitdir=gitdir)
        if len(raw) != sizes[oid] or b"\x00" in raw:
            raise GitDataError("Binary or inconsistent Git blobs are unsupported")
        try:
            texts[oid] = raw.decode("utf-8", errors="strict")
        except UnicodeError as error:
            raise GitDataError("Selected source must be valid UTF-8 text") from error
    files, patches = [], []
    for path, old_oid, new_oid in entries:
        if old_oid == new_oid:
            raise GitDataError("Every selected file must contain committed text changes")
        old_text, new_text = texts.get(old_oid), texts.get(new_oid)
        zero_patch = _diff(repo, gitdir, base_commit, head_commit, path, 0)
        old_changed, new_changed = _changed_lines(zero_patch)
        if not old_changed and not new_changed:
            raise GitDataError("Every selected file must have changed source lines")
        for text, changed in ((old_text, old_changed), (new_text, new_changed)):
            count = 0 if text is None or text == "" else len(text.split("\n")) - int(text.endswith("\n"))
            if any(line < 1 or line > count for line in changed):
                raise GitDataError("Changed-line evidence is outside its source text")
        files.append({"path": path, "base_text": old_text, "head_text": new_text,
                      "changed_base_lines": old_changed, "changed_head_lines": new_changed})
        patches.append(_diff(repo, gitdir, base_commit, head_commit, path, 3))
    return {"schema_version": 1, "base_commit": base_commit, "head_commit": head_commit,
            "files": files, "diff": "".join(patches)}
