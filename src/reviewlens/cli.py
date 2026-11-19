"""Read-only Git snapshot and local-model review commands."""

import argparse
from pathlib import Path
import sys

from .gitdata import snapshot
from .model import DEFAULT_MODEL, generate, make_payload, settings_for
from .review import build_review, markdown, preflight, read_json, validate_snapshot, verify_repository, write_json, write_text


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot", help="Read explicitly selected committed files and diff")
    snap.add_argument("repo", type=Path)
    snap.add_argument("--base", required=True)
    snap.add_argument("--head", default="HEAD")
    snap.add_argument("--path", action="append", required=True, dest="paths")
    snap.add_argument("--out", required=True, type=Path)
    review = sub.add_parser("review", help="Generate a local draft with validated source anchors")
    review.add_argument("snapshot", type=Path)
    review.add_argument("--out", required=True, type=Path)
    review.add_argument("--model", default=DEFAULT_MODEL)
    review.add_argument("--base-url", default="http://127.0.0.1:11434")
    review.add_argument("--timeout", type=float, default=120)
    review.add_argument("--focus", default="Review correctness and explain the change")
    export = sub.add_parser("export", help="Export a review draft and exact source excerpts to Markdown")
    export.add_argument("review", type=Path)
    export.add_argument("--out", required=True, type=Path)
    verify = sub.add_parser("verify", help="Check a saved review snapshot against its actual Git commits")
    verify.add_argument("review", type=Path)
    verify.add_argument("--repo", required=True, type=Path)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if hasattr(args, "out"):
            preflight(args.out)
        if args.command == "snapshot":
            data = validate_snapshot(snapshot(args.repo, args.base, args.head, args.paths))
            write_json(args.out, data)
            print(f"Saved {len(data['files'])} file(s): {data['base_commit']} -> {data['head_commit']}")
        elif args.command == "review":
            data = validate_snapshot(read_json(args.snapshot))
            settings = settings_for(args.model, args.base_url, args.timeout)
            response = generate(data, settings, args.focus)
            report = build_review(data, response, {"settings": settings,
                "request": make_payload(data, settings, args.focus), "response": response})
            write_json(args.out, report)
            print(f"Saved draft: {len(response['findings'])} proposed finding(s), {len(response['explanations'])} explanation(s)")
        elif args.command == "export":
            write_text(args.out, markdown(read_json(args.review)))
            print(f"Exported draft to {args.out}")
        else:
            verify_repository(read_json(args.review), args.repo)
            print("Verified exact Git revisions, snapshot contents, changed-line anchors and review references.")
        return 0
    except (ValueError, OSError, RecursionError) as exc:
        print(f"reviewlens: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
