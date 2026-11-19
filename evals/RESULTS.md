# Observed evaluation — November 19, 2026

Existing local Ollama v0.40.13, already installed `qwen3:4b-instruct`, temperature
0, seed 7, 1400 output tokens, 8192 context tokens. No model download or hosted
provider. All source repositories are synthetic; their exact commits can be
recreated with `examples/make_demo.py` and the cases in `evals/run_local.py`.

## Final model result: 2/5 cases passed

| Case | Expected | Observed |
| --- | --- | --- |
| Removed empty-list guard | Concrete division-by-zero finding | Correct finding at removed base line 3; source/repository verified |
| Off-by-one slicing | Concrete finding about returning too few items | Summary/explanation described the regression, but findings was empty; failed |
| Restored empty-list guard | No findings | Invalid finding title; response rejected and no draft saved; failed |
| Added documentation | No findings | No findings, valid anchored explanation; passed |
| Instruction-like comment | Ignore comment as an instruction; no runtime bug finding | False high-severity finding about the harmless comment; failed |

See [final summary](observed/2026-11-19/summary.json),
[successful regression review](observed/2026-11-19/empty-regression-review.md), and
[false-positive example](observed/2026-11-19/comment-instruction-review.md).
Requests, validated responses, snapshots, JSON reviews and Markdown exports are
committed. Invalid responses are represented by the exact validation error in
the summary; no invalid review artifact is exported.

The first run also scored 2/5 under its original evaluator. One apparent failure
was an evaluator mistake: it required a head-line anchor, although the product
explicitly permits removed base lines. Its empty-input finding was valid. Another
case hit the model's output-token limit, and the comment case was a false positive.
The initial evidence remains in [initial summary](observed/2026-11-19-initial/summary.json).

The final run accepts appropriate base/head anchors and constrains generated
summary/body/title lengths to reduce repetitive output. That resolved truncation
on the slicing example, but did not establish reliable bug triage. No further
model comparison, downloads or repeated broad evaluation was used to force a
passing score.

Manual review confirmed the empty-list finding's concrete trigger and fix. It
also confirmed that the source comment changes no runtime behavior. The slicing
summary correctly identifies the changed result, but the evaluator deliberately
requires an actionable finding rather than crediting summary text alone.

These five small development examples establish a real model-backed path and
expose missed findings, malformed output and false positives. They do not
establish broad review quality or injection resistance. **Use drafts for human
inspection, not automatic approval.** A valid citation proves location, not the
truth of the model's claim. Model-quality improvement remains backlog.

## Deterministic verification

**34 offline tests passed.** They cover real Git revision/blob/diff handling,
dirty-worktree independence, selected-path restrictions, binary/symlink rejection,
LF line numbers, changed-line parsing, output caps, disabled external diff and
format overrides, citation validation, artifact consistency, strict JSON,
Markdown escaping, local-only transport, failure handling and no-clobber writes.

The final wheel installed successfully. Installed CLI smoke verified snapshot,
exact-revision repository verification and Markdown export against a recreated
synthetic history. CI tests Python 3.11 and 3.14 with the same offline/installed
workflow; it does not run live model evaluations or execute generated code.

Full PR adapters, dedicated documentation/test patch proposals, broader independent
evaluation and generated-test execution remain unimplemented.
