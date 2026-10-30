# Artel

**English** · [Русский](README.ru.md)

Local AI workers for your Jira workflow, with a dashboard to see and direct their work.

Artel runs on your own machine. Its workers—called **daemons**—pick up scoped Jira tasks,
implement them through GigaCode CLI, review the changes, and report back to Jira.
Each daemon serves a project or configuration item and can route work to several repositories.

![Artel dashboard: a city with two office buildings](docs/images/city-overview.jpg)
*Demo installation with simulated workers and tasks. The office scene uses separately installed assets.*

## What you can do

| Capability | How it works |
|---|---|
| Run a team | Start the dashboard and configured daemons together; organize workers into named offices and buildings. |
| Give workers different roles | Choose developer, tester, or custom profiles; set a subagent and instructions for seven workflow stages. |
| Follow execution | Watch GigaCode events and tool activity as they arrive, inspect results, and toggle daemon features. |
| Control the next attempt | Exclude tasks, pause retries, approve a repeat, or request rework after requirements change. |
| Improve between tasks | Revisit changed backlog stories, process Bitbucket PR feedback, run retrospectives, and verify memory candidates against code and tests. |
| Understand the workload | Filter task histories and analytics, browse records 20 at a time, and export task statistics as CSV. |

Jira and **Bitbucket Server / Data Center** use Python REST clients; these operations do not
depend on the model's MCP connections. Linked frontend tasks wait for configured backend
readiness. A `BLOCKED` result asks for clarification in Jira instead of repeatedly retrying.

<details>
<summary>More screenshots</summary>

![Task outcomes, generation time, and token usage](docs/images/statistics.jpg)
*Statistics from simulated demo tasks; no production project data is shown.*

![Per-daemon prompt editor](docs/images/prompts.jpg)
*Selecting the tester profile for a demo worker. The dashboard and reference documentation are currently in Russian.*

</details>

## Quickstart

You need **Python 3.9+**, **Git**, and a separately installed **GigaCode CLI**. Artel itself
has no third-party Python runtime dependencies, Node.js requirement, or CDN dependency.
Give every daemon a separate working clone with an `origin` remote and access to its base branch.

1. Clone this repository and enter its directory:

   ```bash
   git clone https://github.com/Falikor/artel.git
   cd artel
   ```

2. Copy [the single-repository template](config/example.json.sample) to `config/team.json`.
   For multiple repositories, use [the services template](config/example-services.json.sample).
   Files ending in `.sample` are not launched.
3. Set `jira.url`, `jira.project`, `jira.status_analysis`, `jira.status_ready`, and
   `general.repo_path`. For a `main` base, set both `general.base_branch` and
   `general.base_branch_create_from` to `"main"`. Replace or remove the template's optional
   epic, configuration-item, and Jenkins settings.
4. Create `tmp/.env` with `JIRA_TOKEN=…`, or a project-prefixed token such as
   `TEAM_JIRA_TOKEN=…` when `jira.project` is `TEAM`. Add Bitbucket/Jenkins credentials only
   when enabling those integrations.
5. Install [the executor subagent](subagents/README.md) for the OS user running the daemons
   and set up OpenSpec in the working repositories. Set `general.require_success_marker: true`
   to require an explicit successful completion signal.
6. Validate the configuration, then start Artel if validation succeeds:

   ```bash
   python3 artel.py check
   python3 artel.py up
   ```

The [dashboard](http://127.0.0.1:8765/) opens automatically. Use `up --no-browser` to skip opening it.

**Windows:** in PowerShell, use `py -3 -X utf8 artel.py check`, followed by
`py -3 -X utf8 artel.py up`, or run `start-artel.cmd` after setup. Use JSON paths such as
`C:/work/service` and test commands appropriate for your OS. See [operations](docs/OPERATIONS.md).

**Office artwork:** the licensed PNG/JSON scene assets shown above are **not included in this
repository**. Install a compatible asset pack you have permission to use in
`office_dashboard/assets/`, or set `OFFICE_ASSETS` to its directory before starting Artel.
See [asset setup](office_dashboard/assets/README.md) for the required structure.
The full animated office scene requires these assets.

## Everyday operation

```bash
python3 artel.py status          # Show running processes
python3 artel.py restart team    # Reload config/team.json
python3 artel.py down            # Stop Artel; interrupts current work
```

Closing the browser does not stop the service. For updates that wait for current tasks,
use the [managed updater](UPDATE.md) with `--managed`: it backs up local data, waits for work,
updates code, and restarts the previous processes with their settings.

The dashboard binds to `127.0.0.1` and has no login. Anyone who can reach it can access logs
and controls; keep that in mind before exposing it beyond the local machine.

## Documentation

The guides below are currently in Russian.

| Topic | Guide |
|---|---|
| Stuck tasks, missed tasks, and paused workers | [Runbook](docs/RUNBOOK.md) |
| Configuration keys, defaults, environment variables, and services | [Configuration reference](docs/CONFIGURATION.md) |
| Roles, subagents, and per-stage instructions | [Prompts](docs/PROMPTS.md) |
| Processes, Windows, logs, and backups | [Operations](docs/OPERATIONS.md) |
| Branches, dependencies, reviews, retries, and changed requirements | [Task lifecycle](docs/WORKFLOW.md) |
| Backlog research and pull request feedback | [Backlog](docs/BACKLOG.md) · [Bitbucket](docs/BITBUCKET.md) |
| Memory verification and retrospectives | [Memory](docs/MEMORY.md) |
| Screens, themes, offices, seating, and statistics | [Dashboard](docs/DASHBOARD.md) |
| Safe updates and release history | [Update and recovery](UPDATE.md) · [Changelog](CHANGELOG.md) |
| UI architecture and regression checks | [Dashboard architecture](office_dashboard/README.md) · [Tests](tests/README.md) |

## Local data

`config/` holds installation settings, `tmp/.env` holds secrets, `memory/` holds learned knowledge,
and `logs/` holds history and runtime state. Dashboard JSON files store names, characters,
prices, office/building names, and seating. These local files are excluded from Git.

The updater preserves this data. Do not replace a working installation by unpacking an archive
over the entire directory; include external data paths in backups with `--data-path`.
Scene artwork has [separate license terms](office_dashboard/assets/LICENSE_EN.txt).
