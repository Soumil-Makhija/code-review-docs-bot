# Review Lens

Read an explicitly selected local Git diff, ask an installed local model for a
code explanation and proposed findings, then inspect a source-anchored Markdown
draft. Every snapshot records the exact base and head commit IDs. Python 3.11+,
standard library at runtime, no paid API or account integration.

## Try it

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .

# Create a synthetic repository with a removed empty-input guard.
python3 examples/make_demo.py /tmp/reviewlens-demo
.venv/bin/reviewlens snapshot /tmp/reviewlens-demo --base HEAD~1 --head HEAD \
  --path calc.py --out snapshot.json
```

Start your separately installed Ollama server with an **already installed**
`qwen3:4b-instruct` model. Review Lens does not start services or download models.

```sh
.venv/bin/reviewlens review snapshot.json --out review.json
.venv/bin/reviewlens verify review.json --repo /tmp/reviewlens-demo
.venv/bin/reviewlens export review.json --out review.md
```

The demo removes the guard returning `0` for an empty list. The changed code
divides by `len(values)`, so an empty list raises `ZeroDivisionError`. The saved
review proposes restoring the guard and cites the changed line. Inspect an
[observed review draft](evals/observed/2026-11-19/empty-regression-review.md).

For your own selected repository, pass a base and head revision and repeat
`--path` for each file. Only committed regular text files are supported. Dirty
working-tree and staged changes are excluded. No repository URL or account is
needed. A file must have text-line changes between the selected commits.

## What gets checked

1. Resolve both Git revisions to full commit IDs. Read only the selected paths
   from committed blobs; capture their actual base/head source, diff and changed
   line sets. Added/deleted text files work; rename detection is disabled, so
   choose the old/new paths explicitly for a rename.
2. Send that snapshot, with numbered source lines, to the loopback-only local
   model. Require a structured summary, 1–3 explanations and 0–3 findings. Findings
   must include an exact selected path, base/head side, changed line, severity,
   title and reason. The model is instructed to report introduced concrete bugs,
   avoid speculative/style findings, and return no findings for a clean change.
3. Reject invented files, missing source lines, findings anchored only to unchanged
   context, invalid severities, repeated anchors, duplicate JSON keys, nonfinite
   JSON constants, malformed or truncated responses. Explanations may cite valid
   unchanged context within the selected files.
4. Store a draft review with the complete snapshot, its canonical SHA-256, model
   settings/request/response and validated findings. Markdown export inserts the
   **exact original source line**, chosen by the program, beside each citation.
   Model prose is escaped as Markdown text and source fences are safely delimited.

`verify` reopens the local Git repository, resnapshots the exact saved revisions
and paths, and compares the committed source, diff, changed-line evidence and
review anchors. It requires no model and does not execute source code. A moved
clone with the same commits is acceptable. The snapshot hash detects incidental
edits; it is not a signature. Coordinated edits to the stored revisions and
evidence can describe a different valid review. A valid anchor also does not prove
that the model's reasoning is correct or that its finding is useful.

The tool saves drafts only. It has no PR-comment, message, patch-application,
commit, push or generated-test execution command. The Markdown explanation is a
reviewable documentation proposal; no source or documentation file is rewritten.
The builder's public repository push is separate from this application's behavior.

## Limits and settings

- Up to 8 explicitly selected relative file paths; no directories, traversal,
  symlinks, submodules or `.git` components. Selections are literal, so glob-like
  names do not expand. Paths are sorted for deterministic snapshots.
- Combined base/head source is capped at 20 KiB; source must be UTF-8 without NUL.
  Each file side is limited to 500 lines. Line numbers count LF-delimited Git
  source lines, starting at 1; Unicode separators are not extra lines.
- Each Git command has a 10-second timeout and a streaming 256 KiB limit per
  output stream. Hooks, paging, external diff, text conversion, fsmonitor,
  replacement objects and lazy partial-clone fetching are disabled. Snapshot
  commands use a bare Git view to avoid worktree source/attribute substitutions.
  Local repository configuration is still parsed. Review Lens is a read-only
  client of the installed Git, not an OS sandbox for hostile Git metadata.
- Snapshots are capped at 80,000 serialized bytes; model prompts at 28,000 bytes;
  model responses at 128,000 bytes; JSON artifact reads at 512,000 bytes. Select a
  smaller change if source/numbering/diff overhead exceeds the prompt budget.
- `review --model NAME --base-url http://127.0.0.1:11434 --timeout 120` configures
  inference. Numeric loopback HTTP only; redirects and environment proxies are
  refused. Timeout must be greater than 0 and at most 180 seconds. Model options
  are temperature 0, seed 7, 1400 output tokens and 8192 context tokens.
- **Selected committed code and diff are sent to the configured local server.**
  Other files and remote repositories are not collected. Artifacts contain full
  selected source, filenames, revisions and model output. Keep private-code
  artifacts private. All committed examples in this repository are synthetic.
- Outputs require an existing parent directory and a new destination. They are
  published atomically without overwriting files. An existing review output is
  rejected before inference. Exit `0` means the command succeeded, including a
  draft with no findings; exit `2` means input, Git, I/O, model or validation failure.

## Validate

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 evals/run_local.py --out /tmp/reviewlens-evaluation
```

Offline tests cover actual Git histories, added/deleted files, literal paths,
dirty-worktree independence, disabled external diff execution, malformed hunks,
limits, invalid citations, artifact corruption, escaped exports, local-only
transport, provider failures and no-clobber writes. CI tests Python 3.11 and 3.14,
installs the package and exercises snapshot/verify/Markdown export on the demo.
CI does not need a model and executes no model-proposed code.

The real-model evaluation includes two seeded bugs, an actual fix, a documentation
change and an instruction-like source comment. It checks useful bug anchors and
false positives, while retaining full prose for human assessment. See
[observed results](evals/RESULTS.md). Small synthetic cases do not establish
general review quality, complete bug detection or injection resistance.

Next checkpoints: broader independent changes, clearer finding triage, explicit
documentation/test proposal files, and a separately authorized PR adapter.
Generated-test execution would require a declared trusted or isolated environment.
