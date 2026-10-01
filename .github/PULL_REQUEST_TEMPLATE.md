<!--
Thanks for contributing. Keep the diff to what the change requires — no drive-by
reformatting, no unrelated dependency bumps. A reviewer should be able to read
the diff and see only this change.
-->

## What this changes

<!-- One or two sentences. What a reader needs to know before looking at the diff. -->

## Linked issues

<!--
Closes #NN for every issue this PR fully resolves. One PR may close several
issues if they share a root cause. If this PR only partially addresses an issue,
link it with "Refs #NN" and say what is left.
-->

Closes #NN

<!--
A pull request that fixes nothing linked should say "None" rather than leaving
the placeholder, so it is obvious the omission was deliberate.
-->

## Type of change

- [ ] Bug fix (non-breaking)
- [ ] Behaviour change (breaking — describe the migration below)
- [ ] New heuristic (`TX-NNN`)
- [ ] Refactor / internal cleanup (no behaviour change)
- [ ] Documentation
- [ ] Build, CI, packaging, or repository infrastructure

## Testing

- [ ] Added or updated tests
- [ ] `pytest tests/ -v` passes with 0 failures
- [ ] New heuristic has **both** a poison-trace test (fires) and a clean-trace test (quiet)

<!--
Paste the actual result, e.g.:

    $ python -m pytest tests/ -q
    139 passed in 0.31s
-->

```

```

## Before / after

<!--
Required for any behaviour change. If a heuristic's output changes, show the
old output and the new output side by side so a reviewer can confirm the change
is the intended one and nothing else moved.
-->

```

```

## Checklist

- [ ] Code follows the existing style; no comments added unless they earn their place
- [ ] All public functions have type hints
- [ ] No new runtime dependencies in the stdlib-only core
- [ ] README / `--help` updated if the CLI surface changed
- [ ] Any new documented command was actually executed, not just written down

## Breaking changes

<!-- If any. Otherwise write "None". -->
None.
