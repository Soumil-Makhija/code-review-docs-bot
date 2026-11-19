"""Validate source anchors and export model output as a local review draft."""

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from .gitdata import snapshot
from .jsonutil import equal, loads


def source_lines(text):
    if not text:
        return []
    result = text.split("\n")
    return result[:-1] if result[-1] == "" else result


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                     allow_nan=False).encode()).hexdigest()


def validate_snapshot(data):
    if (type(data) is not dict or set(data) != {
            "schema_version", "base_commit", "head_commit", "files", "diff"}
            or type(data["schema_version"]) is not int or data["schema_version"] != 1
            or not all(type(data[key]) is str and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", data[key])
                       for key in ("base_commit", "head_commit"))
            or type(data["files"]) is not list or not 1 <= len(data["files"]) <= 8
            or type(data["diff"]) is not str or not data["diff"]):
        raise ValueError("Invalid version-1 Git snapshot")
    seen = set()
    for file in data["files"]:
        if (type(file) is not dict or set(file) != {
                "path", "base_text", "head_text", "changed_base_lines", "changed_head_lines"}
                or type(file["path"]) is not str or not 1 <= len(file["path"]) <= 500
                or file["path"] in seen or file["path"].startswith("/")
                or any(p in {"", ".", "..", ".git"} for p in file["path"].split("/"))
                or any(ord(c) < 32 for c in file["path"])):
            raise ValueError("Invalid or duplicate snapshot file")
        seen.add(file["path"])
        for side in ("base", "head"):
            text, changed = file[f"{side}_text"], file[f"changed_{side}_lines"]
            if text is not None and (type(text) is not str or "\x00" in text):
                raise ValueError("Invalid snapshot source text")
            count = len(source_lines(text))
            if count > 500 or type(changed) is not list or any(
                    type(line) is not int or not 1 <= line <= count for line in changed):
                raise ValueError("Invalid changed-line anchors or source exceeds 500 lines per side")
            if changed != sorted(set(changed)):
                raise ValueError("Changed lines must be sorted and unique")
        if file["base_text"] == file["head_text"] or not (
                file["changed_base_lines"] or file["changed_head_lines"]):
            raise ValueError("Snapshot must contain changed text files")
    if len(json.dumps(data, ensure_ascii=False).encode()) > 80_000:
        raise ValueError("Snapshot exceeds 80000 bytes")
    return data


def _text(value, limit, name):
    if (type(value) is not str or not 1 <= len(value.strip()) <= limit
            or any(ord(c) < 32 and c not in "\n\t\r" for c in value)):
        raise ValueError(f"Invalid {name}")


def validate_response(data, response):
    validate_snapshot(data)
    if type(response) is not dict or set(response) != {"summary", "explanations", "findings"}:
        raise ValueError("Model must return summary, explanations and findings")
    _text(response["summary"], 1500, "summary")
    files = {file["path"]: file for file in data["files"]}
    for kind in ("explanations", "findings"):
        entries = response[kind]
        minimum = 1 if kind == "explanations" else 0
        if type(entries) is not list or not minimum <= len(entries) <= 5:
            raise ValueError(f"Invalid {kind} count")
        seen = set()
        for entry in entries:
            fields = {"path", "side", "line", "body"}
            if kind == "findings":
                fields |= {"title", "severity"}
            if type(entry) is not dict or set(entry) != fields:
                raise ValueError(f"Invalid {kind} fields")
            if (type(entry["path"]) is not str or entry["path"] not in files
                    or type(entry["side"]) is not str or entry["side"] not in {"base", "head"}
                    or type(entry["line"]) is not int):
                raise ValueError("Citation must reference a selected file, side and integer line")
            file = files[entry["path"]]
            lines = source_lines(file[f"{entry['side']}_text"])
            if not 1 <= entry["line"] <= len(lines):
                raise ValueError("Citation line is outside the source")
            if kind == "findings" and entry["line"] not in file[f"changed_{entry['side']}_lines"]:
                raise ValueError("Finding must cite an actual changed line")
            anchor = (entry["path"], entry["side"], entry["line"])
            if anchor in seen:
                raise ValueError("Duplicate citation within review section")
            seen.add(anchor)
            _text(entry["body"], 2000, "review body")
            if kind == "findings":
                if type(entry["severity"]) is not str or entry["severity"] not in {"low", "medium", "high"}:
                    raise ValueError("Invalid finding severity")
                _text(entry["title"], 200, "finding title")
    return response


def build_review(data, response, model_info):
    validate_response(data, response)
    return {"schema_version": 1, "snapshot": data, "snapshot_sha256": digest(data),
            "response": response, "model": model_info, "status": "draft"}


def validate_review(report):
    if (type(report) is not dict or set(report) != {
            "schema_version", "snapshot", "snapshot_sha256", "response", "model", "status"}
            or type(report["schema_version"]) is not int or report["schema_version"] != 1
            or report["status"] != "draft" or type(report["model"]) is not dict):
        raise ValueError("Invalid version-1 draft review")
    validate_response(report["snapshot"], report["response"])
    if (set(report["model"]) != {"settings", "request", "response"}
            or type(report["model"]["settings"]) is not dict
            or type(report["model"]["request"]) is not dict
            or not equal(report["response"], report["model"]["response"])):
        raise ValueError("Inconsistent model response metadata")
    if report["snapshot_sha256"] != digest(report["snapshot"]):
        raise ValueError("Snapshot hash mismatch")
    return report


def verify_repository(report, repo):
    validate_review(report)
    data = report["snapshot"]
    observed = snapshot(repo, data["base_commit"], data["head_commit"], [f["path"] for f in data["files"]])
    if not equal(observed, data):
        raise ValueError("Saved snapshot differs from committed Git contents/diff")
    return report


def markdown(report):
    validate_review(report)
    data, response = report["snapshot"], report["response"]
    def escape(text):
        return "".join("\\" + c if c in "\\`*_{}[]<>#+-.!|()~" else c for c in text)
    def excerpt(entry):
        file = next(f for f in data["files"] if f["path"] == entry["path"])
        quote = source_lines(file[f"{entry['side']}_text"])[entry["line"] - 1]
        # A source line may itself contain Markdown fences.
        fence = "`" * max(3, max((len(m) + 1 for m in re.findall(r"`+", quote)), default=3))
        return f"{fence}\n{quote}\n{fence}"
    lines = ["# Review Lens — draft", "", f"Base: `{data['base_commit']}`", "",
             f"Head: `{data['head_commit']}`", "", escape(response["summary"]), "",
             "## Code explanation", ""]
    for entry in response["explanations"]:
        lines += [f"**{escape(entry['path'])}:{entry['line']} ({entry['side']})**", "",
                  escape(entry["body"]), "", excerpt(entry), ""]
    lines += ["## Proposed findings", ""]
    if not response["findings"]:
        lines += ["The model proposed no findings. This is not proof that the changes are correct.", ""]
    for entry in response["findings"]:
        lines += [f"### {escape(entry['title'])}", "",
                  f"Severity: {entry['severity']}. Location: {escape(entry['path'])}:{entry['line']} ({entry['side']}).", "",
                  escape(entry["body"]), "", excerpt(entry), ""]
    lines += ["Draft for human review. Anchors are checked; model reasoning is not verified. No tests were executed or review posted.", ""]
    return "\n".join(lines)


def preflight(path):
    path = Path(path)
    if path.exists() or path.is_symlink():
        raise ValueError(f"Output already exists: {path}")
    if not path.parent.is_dir():
        raise ValueError("Output directory does not exist")
    return path


def write_text(path, text):
    path = preflight(path)
    fd, temporary = tempfile.mkstemp(prefix=".reviewlens-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_json(path, value):
    write_text(path, json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def read_json(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(512_001)
    if len(raw) > 512_000:
        raise ValueError("JSON artifact exceeds 512000 bytes")
    try:
        return loads(raw)
    except (RecursionError, UnicodeDecodeError) as exc:
        raise ValueError("Malformed JSON artifact") from exc
