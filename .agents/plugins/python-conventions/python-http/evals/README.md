# Behavioral evaluations

These are native Claude Code `prompt.md` + `graders/*.md` cases. They exercise
skill discovery, useful composition, limited context loading, preservation of
existing architecture, and the new concurrency/streaming guidance. Prompts carry
their own examples and request code in the reply; no scaffolding, network calls,
filesystem mutations, or agents are needed. Cases use natural requests so skill
activation is measured rather than forced by naming a skill.

Every case has an outcome rubric and a separate skill-use check. Positive skill
checks are indicators when comparing with a no-plugin baseline; negative
skill-use checks apply to both arms. Correct output remains necessary even when
activation succeeds. These cases do not replace executable reference tests.

First run deterministic repository validation, from the repository root:

```sh
python scripts/validate_marketplace.py
claude plugin validate --strict .
claude plugin validate --strict plugins/python-settings
claude plugin validate --strict plugins/python-http
pytest tests/infrastructure
```

The following commands make paid model calls using your Claude Code account;
they are opt-in and keep reports local. Review prompts/graders first. No evals
run automatically in the deterministic CI job.

```sh
# One case, one arm, one run for initial grader calibration.
claude plugin eval ./plugins/python-http --case api-key-only --runs 1 --ablation none --no-publish
# Default three runs per arm, comparing with and without the plugin.
claude plugin eval ./plugins/python-http --no-publish
```

Use `--max-cost-usd` for an explicit spending ceiling. Results land in
`evals/results/`; do not commit them. Compare outcome scores, the baseline delta,
unnecessary skill calls in the trace, input tokens, elapsed time, and estimated
cost. Investigate grader disagreement before changing skill instructions. A
single run is useful for debugging, not a reliable quality claim.

Requires Claude Code 2.1.269 or later. Consult the current
[native eval reference](https://code.claude.com/docs/en/plugin-evals) for field
semantics, cost controls, and result interpretation. This suite has been authored
and structurally checked; do not describe its behavior as passing until actual
model runs have completed.
