# Startup, processes, and logs

[English](OPERATIONS.en.md) · [Русский](OPERATIONS.md) · [Home](../README.md) · [Configuration](CONFIGURATION.en.md) · [Runbook](RUNBOOK.en.md)

## Quick start: Linux, macOS, and Windows

After installing Python, Git, and GigaCode CLI, create working `config/*.json` files from the
`.sample` templates, set repository paths, and put secrets in `tmp/.env`. The `.sample` files
themselves are not started as daemons.

**Linux / macOS:**

```bash
python3 artel.py up
# Do not open a browser / use another port:
python3 artel.py up --no-browser --port 8766
# Stop the supervisor, its daemons, and the dashboard:
python3 artel.py down
```

**Windows 10/11:** double-click `start-artel.cmd`. To stop, use `stop-artel.cmd`.
These launchers switch to the installation directory and enable UTF-8 automatically.
Alternatively, run these commands in PowerShell from the Artel directory:

```powershell
py -3 -X utf8 artel.py up
py -3 -X utf8 artel.py status
py -3 -X utf8 artel.py down
```

`up` starts the dashboard at `http://127.0.0.1:8765/`, starts the supervisor with all enabled
configurations, and opens a browser. Calling it again reuses the running processes.
If the port is occupied, the command reports an error **before starting any daemons**.
To change the port, run `down` first. Closing the browser does not stop Artel.
`down` performs a normal daemon stop: it interrupts current work while preserving recovery
mechanisms; it does not wait for tasks to finish. Daemons started outside the supervisor do not
belong to it and are not stopped by this command.

Dashboard log: `logs/artel-dashboard.log`; launch metadata: `logs/artel-dashboard.json`.
You can still start `office_dashboard/server.py` manually; `down` does not stop such a dashboard.
Configure startup at OS login separately using your operating system's facilities.

On Windows:

- Git and GigaCode must be available to the current user through `PATH` or an absolute executable path.
  Check `git --version`, `gigacode --version`, and `py -3 -X utf8 artel.py check`.
- In JSON, paths such as `C:/work/service` are convenient; backslashes must be doubled.
- Test commands must work on Windows, for example `mvnw.cmd`, `gradlew.bat`, `npm.cmd`, or `python`.
  Automatic detection accounts for Windows when selecting Maven, Gradle, and npm/pnpm/yarn.
  For nonstandard builds, set `memory.verify_commands` and `bitbucket.test_commands` as argument arrays.
- Locks use Windows byte-range locking; checking a PID does not signal the process.
  The CLI and tests run through a separate Windows Job Object, which terminates remaining child
  processes when the controlling process exits.
- GigaCode logs are written to the system temporary directory (`tempfile.gettempdir()`, usually
  `%TEMP%` on Windows). The dashboard and archiver use the same location.
- `update_artel.py`, including `--managed`, currently targets Linux/macOS and explicitly rejects
  Windows. On Windows, stop Artel, back up the installation, and update only the code, preserving
  `config/`, `tmp/`, `memory/`, `logs/`, and JSON settings in `office_dashboard/`.

This version was validated on macOS. The native Windows Job Object test is included in
`tests/test_portable_workspace.py`, but is skipped on macOS. Running with corporate GigaCode
on a real Windows system has not yet been verified. WSL can be used with Linux paths and the Linux CLI.

## Running through the supervisor (recommended)

```bash
python3 artel.py start              # Start all daemons from config/*.json in the background
python3 artel.py status             # Processes, activity, crash counts, and versions
python3 artel.py restart            # Restart all daemons, for example after a code update
python3 artel.py restart hrppa      # Restart one daemon by its configuration filename
python3 artel.py restart --outdated # Restart only daemons running an older code version
python3 artel.py check              # Check every configuration without starting daemons
python3 artel.py memory forget-explore   # Remove lessons recorded by backlog exploration
python3 artel.py archive            # Rotate large logs and archive old logs now
python3 artel.py stop               # Stop all supervised daemons
```

Example status output. The CLI currently uses Russian messages; changing the web UI language
does not translate terminal output:

```text
Супервизор: работает, pid 5909 · версия кода демонов 2.0.0
ДЕМОН   КОНФИГ              PID   СОСТОЯНИЕ       ЭТАП        ЗАДАЧА     ПЕРЕЗАП.  ВЕРСИЯ
Марина  config/paymt.json   5911  работает        ждёт задач  —          0         2.0.0
Олег    config/hrppa.json   5912  работает        пишет код   HRPPA-514  1         2.0.0
Игорь   config/crmx.json    —     ошибка конфига  —           —          3         —
```

The supervisor restarts crashed daemons with increasing delays (5 → 10 → 20 … seconds,
capped at 5 minutes), discovers new configurations, and stops daemons whose configurations
were removed. A daemon that fails its startup checks is retried every 5 minutes. A daemon
stopped manually (`kill`) is not restarted until `artel restart`.
Each daemon's terminal output goes to `logs/{config}-stdout.log`; the supervisor log is
`logs/artel-supervisor.log`. Under the supervisor, the daemon log is not duplicated in
`stdout.log`: that file contains GigaCode terminal output and crash tracebacks, while the
normal daemon log is `logs/{CI}-agent.log`.

## Logs and archives

Old logs are gzip-compressed into **`logs/archive/YYYY-MM/`** instead of being lost or growing
indefinitely in their active files. Archives are retained indefinitely; remove monthly folders
manually when they are no longer needed:

- The daemon log, its `stdout.log`, the supervisor log, and `jira-agent.log` are rotated when a
  file exceeds `logs.max_mb` (20 MiB): contents move to the archive and the active file starts
  again, without disrupting the writing process.
- GigaCode logs (`gigacode_<KEY>*.log` in the system temporary directory) older than
  `logs.cli_keep_days` (14 days) move to `logs/archive/YYYY-MM/gigacode/`. When a task runs again,
  the previous run is archived immediately instead of being overwritten.

The archiver runs from the supervisor every 10 minutes, from each daemon every hour, and on demand
with `python3 artel.py archive`. The manual command also reports archive usage by month. Only one
archiver runs at a time. Task history, delivery history, and outcomes (`*-history.jsonl`,
`*-delivered.jsonl`, `*-outcomes.json`) are not archived: statistics depend on them, and they grow
with task records. To read an archive, use `zcat logs/archive/2026-10/ci3191860-agent-*.log.gz | less`;
to search it, use `zgrep`.

[Configuration reference](CONFIGURATION.en.md).

The supervisor does not read per-daemon configuration values for its own archive settings;
provide the corresponding environment variables for it.

To start Artel with the computer, configure the OS to run `python3 /path/to/artel.py run`
(the supervisor runs in the current process). On macOS use `launchd` with a `KeepAlive` plist;
on Linux use `systemd` with `Restart=on-failure`. Set the working directory to the project directory.

## Running one daemon manually

```bash
python3 jira_to_gigacode.py config/hrppa.json             # Run in this terminal
python3 jira_to_gigacode.py config/hrppa.json --check     # Check the environment only
python3 jira_to_gigacode.py config/hrppa.json --dry-run   # One preview cycle, without task changes
python3 jira_to_gigacode.py --version
```

**Startup checks** run every time: repository and `origin`, the branch specified by
`general.base_branch`, GigaCode CLI, Jira token and project, Jenkins job and parameters,
reviewer CLI, memory file, and backlog statuses. Errors prevent startup; warnings do not.

**Stopping:** `kill <pid>` (SIGTERM) interrupts GigaCode if it is running and exits the daemon
within seconds. An interrupted run is not treated as completed work: on the next run, its
commits are set aside under `refs/ai-team-interrupted/…`. An explicit approval in **Retries**
may be required before the task starts again; see the [Runbook](RUNBOOK.en.md).

## Files written to `logs/`

Here, `{CI|project}` means the instance key derived from the CI identifier or Jira project.

| File | Purpose |
|---|---|
| `{CI\|project}-agent.log` | Instance log (`-dryrun.log` and `-check.log` are preview/check runs) |
| `{CI\|project}-state.json` | Current stage, issue, version, and heartbeat every 10 seconds, used by the dashboard |
| `{CI\|project}-history.jsonl` | One record per completed task attempt: outcome, time, environment, and tokens, used for statistics |
| `{CI\|project}-retries.json` | Exclusions, pauses, approvals, and retry state, preserved across restarts |
| `{CI\|project}-blocked.json` | Executor questions and requirements fingerprints for BLOCKED waits |
| `{CI\|project}-notifications.json` | Delivery queue and Jira comment IDs for decisions requiring the operator |
| `{CI\|project}-requirements.json` | Separate rework queue and outcomes |
| `{CI\|project}-features.json` | UI feature overrides and their revision |
| `{CI\|project}-cli-events.json` | Bounded event window for the current/latest GigaCode execution |
| `{CI\|project}-pr-review-*.json` | PR feedback processing, prepared replies, and uncertain sends |
| `{CI\|project}-pending-transitions.json` | Tasks whose code was pushed but whose Jira transition failed; only the transition is retried |
| `{CI\|project}-issue-notes.json` | Review findings for the next task attempt |
| `{CI\|project}-explored.json` | Backlog tasks already explored |
| `{CI\|project}-proposals.jsonl` | One record per backlog exploration: comment publication, time, and tokens, used for statistics |
| `{CI\|project}-delivered.jsonl`, `{CI\|project}-retro.json` | Delivery history and retrospective tracking |
| `{CI\|project}-outcomes.json` | Delivered-task outcomes such as merged, edited by people, or abandoned, used for statistics |
| `archive/YYYY-MM/` | Old gzip-compressed logs; see “Logs and archives” |
| `{CI\|project}-poke`, `{CI\|project}-stop` | Dashboard request flags for “check Jira now” and “stop”; the daemon removes them itself |
| `artel-supervisor.*`, `{config}-stdout.log` | Supervisor state/logs and supervised daemon terminal output |

## GigaCode tokens

After each run (generation, review, rework, or exploration), the daemon tries to obtain token
usage from these sources, in order:

1. `general.tokens_regex` in the configuration.
2. JSON usage statistics in the CLI result; the current adapter uses `stream-json`.
3. Output lines such as `Total tokens: 12 345`, `Input tokens: …`, or the Russian `Токенов: …`.
4. Chat recordings (`--chat-recording` is already enabled) under `~/.gigacode`, `~/.qwen`,
   `~/.gemini`, or `general.gigacode_chats_dir`, modified during the run.

Detected usage is written to the log (the Russian message `Токены GigaCode: всего …`), history,
the issue report, and statistics. If that log line is absent, your CLI may use another format:
set `general.tokens_regex` or `general.gigacode_chats_dir`. Without usable data, statistics show
“—” rather than inventing a value.

## Daemon version

The code version is `__version__` in `jira_gigacode/__init__.py`. The daemon writes it to
`state.json`; the dashboard and `artel status` flag daemons that have not been restarted after
a code update. Update the version for each release, then run `python3 artel.py restart --outdated`.

## Tests

```bash
python3 -m unittest discover -s tests     # No external Jira, Jenkins, or GigaCode required
```

See the [test documentation](../tests/README.en.md) for details.
