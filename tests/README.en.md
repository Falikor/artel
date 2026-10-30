# Tests for the Jira → GigaCode daemon

[Русский](README.md) · **English**

Run from the project root, beside `jira_to_gigacode.py`. The Python suite requires
Python 3.9+ and Git:

```bash
python3 -m unittest discover -s tests                      # full suite; takes a few minutes
python3 -m unittest discover -s tests -v                   # include test names
python3 -m unittest discover -s tests -p 'test_git_flow.py' # one file
TEST_LOGS=1 python3 -m unittest discover -s tests          # daemon logs and fake CLI output
```

No external network, Jira, Jenkins, or GigaCode installation is required. HTTP tests run
against local loopback servers:

- **Git** is real and operates on temporary repositories with a local bare origin.
  The developer's global Git configuration, including commit signing and hooks, is disabled.
- **GigaCode** is replaced by `tests/fake_gigacode.sh`. It identifies the caller from the
  prompt and follows environment variables: generation uses `FAKE_MODE` (commit with a
  marker, no marker, temporary files only, a commit on develop, hanging, and other cases);
  review uses `FAKE_REVIEW` (`approve`, `changes`, or `none`, optionally comma-separated
  per call, such as `changes,approve`); revision uses `FAKE_REWORK`; exploration uses
  `FAKE_EXPLORE`. `FAKE_PROMPT_DIR` saves all commands received by the CLI.
- **Jira** uses `FakeJira` in `tests/helpers.py`, replacing `jira_client.jira_request`
  with issues, statuses, transitions, labels, and comments.
- **Jenkins** replaces `urlopen` in `jira_gigacode.jenkins`.
- Daemon environment variables such as `JIRA_TOKEN` and `REPO_PATH` are removed during
  tests, and `tmp/.env` is not read.

| File | Coverage |
|---|---|
| `test_config.py` | Environment/configuration precedence, project prefixes, `.env`, CI and instance keys, log migration, and CLI flags. |
| `test_prompt_control.py` | Per-daemon prompt settings, validation and revision conflicts, task/background-operation boundaries, actual stdin passed to the fake CLI, save/reset, and read-only HTTP API. |
| `test_tokens.py` | Token extraction from text, JSON, and chat records without double counting. |
| `test_branch_config.py` | Configurable base branch, main-only repositories, environment and service overrides, inheritance by background checks, and protected-base behavior. |
| `test_git_flow.py` | Successful generation with/without a marker, timeouts and recovery, remote delivery, temporary files, commits on develop, and base branches from comments. |
| `test_jira_and_reports.py` | JQL and filters, missing statuses, labels and Jenkins deployment, cooldowns, report comments, and secret masking. |
| `test_startup_and_dry_run.py` | `--check`, `--dry-run`, and launching the complete script as a process. |
| `test_review.py` | Review verdicts, fixes, transition blocking, findings carried into the next attempt, and reviewer isolation from the working clone. |
| `test_experience.py` | Agent lessons, experience-file deduplication and limits, manual mode, experience in subsequent prompts, and task notes. |
| `test_explore.py` | Backlog exploration comments, duplicate prevention, re-exploration after changes, command templates, repository preservation, and Markdown → Jira conversion. |
| `test_requirements_snapshot.py` | Fingerprints of summary, description, and discussion; human changes are included, while verified Artel messages and status changes do not restart work. |
| `test_blocked.py` | Separate BLOCKED waiting state, questions and direct backlog transitions, no retry without clarification, and resumption of ordinary tasks and rework. |
| `test_notifications.py` | Persistent Jira notifications, updating the daemon's existing comment, and recovery from errors or uncertain POST outcomes without duplicates. |
| `test_supervisor.py` | Configuration-based startup, delayed restarts, configuration errors, manual stopping, removed configurations, versions, and `--outdated`. |
| `test_routing.py` | Service selection by title/labels, one clarification question with reconsideration after edits, service-repository execution, and checks across all repositories. |
| `test_dashboard_data.py` | Token prices, task costs, CSV, idle time since the last task, CI, service, and cache usage in history. |
| `test_stop_control.py` | Dashboard stopping, flag files, interrupting GigaCode, and Stop/Start controls. |
| `test_retro.py` | Merged unchanged, human-edited, squash-merged, open, and deleted branches; follow-ups, comments, scheduling, lessons, and reports. |
| `test_log_archive.py` | Rotation and monthly archives: copytruncate, GigaCode log age/repeated runs, locking, and no duplicate stdout log under the supervisor. |
| `test_quality.py` | Retrospective task outcomes in `outcomes.json` and dashboard totals: shares, weeks, filters, and repeated delivery. |
| `test_tasks_and_proposals.py` | Task-level statistics, failures followed by success as one task, costs across attempts, CSV, card counters, and idle-suggestion history. |
| `test_pr_review.py` | Bitbucket REST, pagination, PR ownership, repeated replies, failures, fix verification, and disputed-case controls. |
| `test_main_loop.py` | Polling passes, transition-only retries, cooldowns and comments, signal handling, and “check now”. |

`test_updater.py` checks transfer of new screens and nested sprites, archive contents
without working data, checksums, rejection of incomplete packages, `--verify-only`, and
rollback when installed-file verification fails. `test_maintenance_update.py` checks
waiting for active tasks and restarting real test processes with their dashboard
parameters preserved.

When adding a scenario, start from `DaemonTestCase` in `helpers.py`. It provides an
isolated environment, `self.make_repo()`, `self.config(work)`,
`self.run_generation(key, cfg, mode)`, and `self.jira`. Add new fake-CLI behavior as another
`case` branch in `fake_gigacode.sh`.

Importing the daemon may create `jira-agent.log` and `logs/` in the project root, just as
normal daemon startup does.

`test_portable_workspace.py` covers interprocess locks, safe PID checks, Windows Job
Objects (Windows only), analytics with incomplete measurements, memory reading and
decisions, HTTP restrictions, isolated `up/down`, repeated startup, and occupied ports.
On Windows, run it separately with:

```powershell
py -3 -X utf8 -m unittest discover -s tests -p test_portable_workspace.py
```

`test_requirements_rework.py` covers the manual-rework queue, cancellation and API
protection, configuration changes, interrupted requests without automatic retries,
unavailable or changed Jira requirements, preserving the old branch, separate accounting,
and an end-to-end run using fake GigaCode.

`node tests/test_office_social.js` checks visits without changing permanent seating,
returning home, interruption by real work, and reactions that respect reduced motion.
Node is needed for interface checks, not to run the dashboard.

Run all JavaScript interface tests with Node:

```bash
node --test tests/test_*.js tests/test_*.cjs
```

`test_prompt_editor.js` covers drafts for separate daemons and stages, previews without
saving, restoring configuration, conflicts, errors and delayed server responses,
settings application through SSE, unsaved-input protection, and demo mode.

`test_dashboard_pagination.js` checks independent 20-record lists, **Show more** through
the full result set, retaining expanded pages during refresh, resetting on filters or
sorting, all journal records beyond the former 400-row cap, full totals, and memory
sources. It also exercises English statistics rendering.

`test_feature_control.py` covers persisted switches, UI precedence over environment and
service settings, revision conflicts, disabling Jira/Jenkins, task boundaries, read-only
and Origin protections, CLI output before a newline or process exit, correct UTF-8
reassembly, and daemon-log isolation.

`test_dependencies.py` checks linked backend/frontend tasks, ordering within one CI,
the frontend `backend-ready` label for a backend in another CI, multiple dependencies,
search pagination, waiting without retries, updating one comment, the rework queue,
dry runs, and background features. The Development API is mocked; branches with code,
empty branches, and deleted branches are checked with real Git against a temporary local
origin. Tests also cover backend repository/base selection and temporary-ref cleanup.

`test_pr_review.py` includes the behavior added in version 2.20.0: TLS without a CA
setting as in the Jira client; system or explicit CA verification; batch analysis of all
PR comments, including replies; one verified commit/push and individual responses;
independent objection verification; partial POST failures; recovery after push; and
migration of the earlier review ledger. Bitbucket and GigaCode are mocked. Git and test
commands run in temporary local repositories.

`test_dashboard_i18n.js`, `test_dashboard_server_messages.js`, and
`test_dashboard_office_language.js` cover RU/EN persistence, changing language while
protecting drafts (including hidden sections), exact server-message translation, and
office labels/dialogue without changing user names. `test_dashboard_locale.py` checks
explicit HTML/accessibility translations, CSV language, and provenance of default
building names. The English statistics scenarios are in `test_dashboard_pagination.js`.

See the [dashboard architecture](../office_dashboard/README.en.md) for UI module boundaries,
the [configuration reference](../docs/CONFIGURATION.en.md) for runtime settings, and the
[update guide](../UPDATE.en.md) for package verification and deployment behavior.
