# Review Lens — draft

Base: `dc252f6a9bca3f81e26f1621e1ad0fcb8d8e992f`

Head: `a851fb5c29afb8d9cc2486fcc083e61d4bd58287`

The \`average\` function in \`calc\.py\` has lost its guard against empty input lists\. The original implementation safely returned 0 when the input list was empty\. The current version removes this guard and directly computes the average, which will raise a \`ZeroDivisionError\` when given an empty list\. This introduces a critical runtime error in a common use case\. A fix would be to restore the guard and return 0 when \`values\` is empty\.

## Code explanation

**calc\.py:2 (base)**

The function \`average\` in \`calc\.py\` has been simplified by removing the empty\-check guard\. Originally, it checked if \`values\` was empty \(i\.e\., \`if not values:\`\) and returned 0 in that case\. This was a valid safeguard to avoid division by zero when \`len\(values\)\` would be zero\. The current version removes this check and directly computes \`sum\(values\) / len\(values\)\`, which will raise a \`ZeroDivisionError\` when \`values\` is empty\. This change removes a critical safety check, making the function potentially fail on empty inputs without any warning or fallback behavior\.

Specifically, the base version \(before change\) had:
\- Line 2: \`if not values:\` \(checks if list is empty\)
\- Line 3: \`return 0\` \(returns 0 if empty\)

The head version \(after change\) removes both lines 2 and 3, leaving only the computation line \(line 4\), which now runs without any guard against empty input\.

This change introduces a critical bug: when an empty list is passed, the function will raise a \`ZeroDivisionError\` because \`len\(values\)\` is 0, and division by zero is undefined in Python\. This behavior is not handled or anticipated in the new code, and users of the function will see a runtime error instead of a safe default value\.

A practical fix would be to reintroduce the guard and return a default value \(like 0\) when the list is empty, as was originally implemented\.

This is a correctness issue, not a style or performance one, and directly affects the function's reliability in real\-world usage\.

Note: The change removes two lines of defensive code, which is a significant shift in behavior and safety\.

The change is not a minor refactoring—it is a removal of a safety check that prevents runtime errors on empty inputs\. This is a high\-risk change without proper justification or fallback behavior\. The function now behaves incorrectly in a common use case \(empty input\)\.

```
    if not values:
```

## Proposed findings

### Division by zero on empty input

Severity: high. Location: calc\.py:2 (base).

The change removes a critical safety check that prevents a \`ZeroDivisionError\` when an empty list is passed to \`average\`\. For example, if \`average\(\[\]\)\` is called, the function will now raise a \`ZeroDivisionError\` because \`len\(\[\]\)\` is 0 and division by zero is undefined\. This is a concrete bug introduced by the change\.

Input: \`average\(\[\]\)\`
Condition: Empty list passed to function
Result: \`ZeroDivisionError\` raised
Fix: Reintroduce the guard \`if not values:\` and return 0 in that case\.

This bug is directly tied to the removal of line 2 and 3 in the base version \(now absent in head\)\. The function no longer handles the empty input case, which was a valid and expected behavior in the original implementation\.

```
    if not values:
```

Draft for human review. Anchors are checked; model reasoning is not verified. No tests were executed or review posted.
