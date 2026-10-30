# Memory and retrospectives

[English](MEMORY.en.md) · [Русский](MEMORY.md) · [Home](../README.md) · [Configuration](CONFIGURATION.en.md) · [Runbook](RUNBOOK.en.md)

## Repository knowledge (`memory/`)

Memory has three layers. A successful run, AI review, or repetition of the same idea
**does not confirm** that a lesson is correct.

- **Permanent rules** live in `<memory.path>.rules.md`. The operator maintains them; the daemon
  does not modify that file. They enter the context first. If they exceed `max_chars`, prompt
  construction fails rather than silently truncating important rules.
- **Confirmed knowledge** consists of records in `<memory.path>.store.json`, with supporting
  evidence, scope, and a verification date. Only these records, together with permanent rules,
  enter the next task's context.
- **Candidates** are new observations from generation, review, rework, and retrospectives.
  The agent may produce **zero lessons**; generic advice and one-task details are explicitly
  discouraged. Candidates do not enter the working context. When enabled, `explore.learn`
  also creates candidates only.

The old `memory/{CI|project}.md` file is preserved unchanged. On first access, its entries are
imported as candidates, not verified rules. The oldest entries beyond the limit are recorded
in history; the complete original text remains in the old Markdown file. Explicitly move
permanent rules into `.rules.md`. Previous entries are never trusted automatically.

Whole records are selected within the context budget: first rules, then confirmed knowledge
whose scope matches a substring of the task text and whose words match the task. A record
without a scope applies to the entire repository. This is simple textual selection, not
semantic retrieval. Exact duplicates are combined with an observation count; case and operators
are preserved. Similar wording is shown during review but is not merged automatically:
“do X” and “do not do X” can be very similar.

[Configuration reference](CONFIGURATION.en.md).

Maintenance runs when memory is read or written and through the `sweep` command. After
90 days, a confirmed record becomes a candidate again and leaves the working context.
Repetition by the agent does not extend its confirmation period. Candidates older than
30 days and records beyond capacity are recorded in the bounded `.history.jsonl` /
`.history.jsonl.1` audit log. History older than that rotation is not retained; the original
legacy Markdown is not deleted. File locking and atomic writes protect the store during
concurrent daemon activity and manual review.

**Automatic candidate verification is enabled by default.** While idle, after exploration,
the daemon checks one candidate, at most once an hour for each memory store. With multiple
services, their own repositories and `memory` settings are used. Verification runs in a
separate Git worktree based on a freshly fetched `memory.verify_base` (default:
`origin/<general.base_branch>`). Tests do not run in the primary working clone.

1. A separate GigaCode call examines the candidate, permanent rules, and confirmed knowledge,
   finds exact code quotations, and selects tests from the available list.
2. The daemon verifies quotations against a specific Git commit and runs the tests itself;
   it does not trust the agent's account of having run them. File/HEAD changes made by the
   verifier prevent confirmation.
3. A second GigaCode call assesses whether the actual results support the entire conclusion.
   Only a directly observable structural fact can be confirmed without executing tests;
   claims about behavior or whether commands work require successful, relevant tests.
4. A confirmed record automatically enters working memory with the commit, quotations,
   command results, and rationale. Contradictions, unclear conclusions, missing relevant
   tests, or failing tests produce `disputed` for operator review. A CLI/network failure
   or timeout leaves the candidate eligible for an automatic retry after 24 hours.

This is model-assisted verification, not formal proof: GigaCode assesses meaning and test
relevance and can be wrong. Select another model through `verify_extra_args` if desired.
A worktree isolates files, **not system permissions or network access**. Project tests run
with the daemon user's permissions; commands mentioned in candidate text are not executed
directly. The daemon does not separately install dependencies or deploy, although build tools
may download dependencies while running tests. Test commands run with `CI=true`.

[Configuration reference](CONFIGURATION.en.md).

For Python, automatic test detection uses `python -B -m unittest discover -s tests` when `tests/`
exists, or `python -B -m pytest -q` when there is `pytest.ini`, a root `conftest.py`, or a pytest
section in `pyproject.toml`. It also recognizes Maven (`mvn test` / `./mvnw test`), Gradle
(`gradle test` / `./gradlew test`), npm/pnpm/yarn (the `test` script in `package.json`), Go
(`go test ./...`), and Rust (`cargo test`). For a monorepo or a nonstandard command, specify
commands explicitly, for example:
`"verify_commands": [["npm", "test", "--", "--run"], ["npm", "run", "typecheck"]`.
Arguments must match the actual project. An empty list disables test execution but still
permits verification of structural facts. Unconfirmed candidates do not affect ordinary tasks.
Automatic confirmation expires after 90 days, and the record is verified again. Disputed
candidates are rechecked only after `retry`; their retention is still bounded by `candidate_days`.

Reviewing memory (replace `memory/t.md` with the daemon's base memory path):

```bash
python3 artel.py memory list memory/t.md --disputed --config config/t.json
python3 artel.py memory retry memory/t.md ID --config config/t.json
python3 artel.py memory approve memory/t.md ID --evidence "Verified make test at commit abc123" --config config/t.json
python3 artel.py memory approve memory/t.md NEW_ID --evidence "Checked the new Makefile" --replaces OLD_ID --scope backend --config config/t.json
python3 artel.py memory reject memory/t.md ID --config config/t.json
python3 artel.py memory sweep memory/t.md --config config/t.json
```

Get `ID` from `list`. Repeat `--scope` for multiple scopes; without it, the knowledge is
repository-wide. `--replaces` lets you merge or supersede an outdated conclusion while
retaining an audit event. The operator is responsible for manual `approve`: that command does
not run tests or verify the truth of the supplied text. After expiry, a record can be approved
again while it still exists among candidates. Without `--config`, default limits and
environment variables apply; pass the daemon's configuration for custom settings. Permanent
rules are not checked for expiry automatically; the operator reviews them.

## Retrospectives: learning from delivered tasks

Every few days (`retro.every_days`, default 7), during the night window (`retro.window`,
default `01:00-05:00` in the computer's local time), and only while idle, the daemon examines
what happened to tasks it delivered at least `min_age_days` (2) days earlier:

- **Whether and how the work was merged:** directly; squashed or manually merged, identified
  by a base-branch commit containing the issue key; still open; or branch deleted without merging.
- **Whether people changed its code:** commits on top of the delivered work before merging
  and the “as delivered → current result” diff.
- **Follow-up changes after merging:** base-branch commits containing the issue key.
- **Jira activity:** the current status and human comments made after delivery.

The daemon gathers these facts itself using Git and Jira only. One GigaCode run per repository
then analyzes what people corrected and why, recurring mistakes, and what to do differently.
Lessons are saved in `.store.json` as candidates with a retrospective source: human actions
provide material for analysis, while the agent's conclusions undergo separate verification.
The complete analysis is stored in `memory/retro/{CI}[-service]-YYYY-MM-DD.md`. Unmerged tasks
wait for another retrospective, up to `max_age_days` (30), after which they are analyzed as-is.

The daemon maintains `logs/{CI}-delivered.jsonl`, recording the branch and commit at delivery.
Tasks delivered before version 2.2.0 are absent from that history; newer tasks are the ones
available for analysis. Each reviewed task's outcome is written to `logs/{CI}-outcomes.json`.
The dashboard uses it for the delivered-task outcomes section in **Statistics**.

```bash
python3 jira_to_gigacode.py config/hrppa.json --retro --dry-run   # Preview collected facts without the agent
python3 jira_to_gigacode.py config/hrppa.json --retro             # Run a retrospective now, without waiting for night
```

[Configuration reference](CONFIGURATION.en.md).
