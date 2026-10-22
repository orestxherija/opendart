# Behavioral evaluations

Seven native `prompt.md` + `graders/*.md` cases check skill discovery, composition,
backend distinctions, and scope. Prompts request replies only; no writes,
database connections, shell, or agent tools are permitted. Positive activation
checks are indicators, not substitutes for correct outcomes. Negative skill-use
checks apply to both comparison arms.

Cases cover SQLite configuration, async ORM loading, PostgreSQL transaction
replay, a dual-backend integration, early-closed streams, migration boundaries,
and preservation of an existing `sqlite3` client.

Run deterministic repository/reference checks first. From the repository root:

```sh
python scripts/validate_marketplace.py
claude plugin validate --strict plugins/python-db
pytest tests/infrastructure tests/python_db
```

Model evals are optional paid runs, separate from deterministic CI:

```sh
claude plugin eval ./plugins/python-db --case sqlite-client --runs 1 --ablation none --no-publish
claude plugin eval ./plugins/python-db --no-publish --max-cost-usd 10
```

Requires Claude Code 2.1.269+ and an authenticated account. Reports stay in ignored
`evals/results/`. Compare outcome quality, activation, unnecessary skill reads,
cost, and baseline delta. Calibrate graders before treating one run as evidence.
See the [native eval reference](https://code.claude.com/docs/en/plugin-evals).

These cases have been authored for structural validation. Do not report their
behavior as passing until model runs have actually completed. Executable
reference tests, including backend tests that were run or skipped, must be
reported separately.
