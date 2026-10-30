# Configuration reference

**English** · [Русский](CONFIGURATION.md)

[README](../README.md) · [Operations](OPERATIONS.en.md) · [Runbook](RUNBOOK.en.md)

One JSON file in `config/` describes one daemon. A daemon can work with one repository or route tasks to several services. The daemon's working repositories are separate Git clones; they are not the Artel installation directory.

This reference covers the public configuration consumed by the current code: defaults, environment variables, precedence, operational consequences, and examples. Fields beginning with `_` are internal state, not user settings.

## Find the setting you need

| Goal | Section |
|---|---|
| Start with one repository | [Minimal developer configuration](#minimal-developer-configuration) |
| Understand which value wins | [Resolution and validation](#resolution-and-validation) |
| Limit which Jira tasks can be taken | [Jira and task selection](#jira-and-task-selection) |
| Choose `main`, `master`, or another base | [Repository and execution](#repository-and-execution) |
| Give a worker a testing or custom role | [Prompts and specialization](#prompts-and-specialization) |
| Route backend and frontend to different repositories | [Multiple services](#multiple-services) |
| Control backend/frontend dependencies | [Linked-task dependencies](#linked-task-dependencies) |
| Require review before completing a task | [Independent code review](#independent-code-review) |
| Bound and verify learned knowledge | [Memory](#memory) |
| Handle pull request feedback | [Bitbucket Server and Data Center](#bitbucket-server-and-data-center) |
| Research backlog stories during idle time | [Backlog exploration](#backlog-exploration) |
| Handle blocked work or changed requirements | [Retries, BLOCKED, and rework](#retries-blocked-and-rework) |
| Run on Windows or override several daemons | [Environment and Windows examples](#environment-and-windows-examples) |

## Resolution and validation

### Configuration sources

For ordinary settings with an environment variable, precedence is:

1. Project-prefixed environment variable, such as `TEAM_BASE_BRANCH`.
2. Unprefixed environment variable, such as `BASE_BRANCH`.
3. A supported per-service override, when that service is selected.
4. The daemon's top-level JSON configuration.
5. The built-in default.

The prefix comes from **`jira.project` in JSON**, not from the filename, display name, CI ID, or the value of `JIRA_PROJECT`. Both the literal project prefix and its uppercase spelling are checked, in that order. Empty environment values are ignored. `tmp/.env` only fills variables absent from the process environment; it does not replace existing variables. An existing but empty process variable therefore prevents the same variable from being loaded from `.env`, although the resolver then ignores its empty value.

There are two explicit dashboard exceptions:

- Saved **On / Off** decisions override environment and JSON values for the supported [feature switches](#feature-switches), including their per-service values. **From config** removes that override.
- Saved **Prompts** settings override the whole normalized top-level `prompts` configuration. Prompts have no environment variables and no per-service overrides. **From config → Save** removes the dashboard override.

These rules do not make the dashboard an override source for arbitrary JSON fields. Display names, characters, office names, buildings, and seating have their own dashboard files.

JSON and environment changes require a daemon restart. Dashboard feature and prompt changes are read at safe boundaries between tasks and background operations; they do not rewrite the instructions of a job already running. Changing behavior or selection scope can require approval before an old task is retried.

### Identity and file names

`jira.project` must exist in JSON even when Jira is disabled. With no `general.ci_id`, the lowercase project key is the daemon's instance ID, for example `team`. With `ci_id: "CI00042"`, the instance ID is `ci42`. The optional `CI` prefix and leading zeros are normalized.

The instance ID identifies memory and runtime files. Renaming the config file or daemon display name does not create a new identity. Two configs with the same normalized CI ID collide; so do two configs for the same project without CI IDs. Give independent daemons distinct instance IDs and distinct working clones. A project-prefixed environment variable affects all daemons whose JSON project is that project, even if their CI IDs differ.

`JIRA_PROJECT` changes the project used by Jira requests, but does not rename the instance or change its environment-variable prefix. Normally keep the query project and JSON project aligned.

### Types, paths, and validation limits

Use native JSON types: booleans `true`/`false`, numbers for intervals, arrays of strings for lists. Environment booleans accept `true/false`, `1/0`, `yes/no`, `on/off`, and `да/нет`, case-insensitively. Integer parsing falls back to the documented default if conversion fails; individual consumers clamp some limits as noted below. A zero value is not a universal way to disable a feature: use its `enabled` switch.

Environment lists are comma-separated, including extra CLI arguments: `REVIEW_EXTRA_ARGS=--model,model-name`. Whitespace is stripped; list values are deduplicated case-insensitively. They are not shell command lines: quoting does not create a multi-word argument, and commas inside an argument cannot be represented by this format. Prefer JSON arrays for precise arguments; the list resolver also normalizes and deduplicates these arrays.

`general.gigacode_chats_dir` is an exception: JSON accepts one path or an array of paths, while its environment variable accepts one path, not a comma-separated list. Test commands are a different type again: arrays of argument arrays, available only in JSON.

Use absolute working-repository and executable paths, especially under a service manager. JSON does not interpolate environment variables or shell syntax. Windows paths can use forward slashes (`C:/work/service`) or escaped backslashes (`C:\\work\\service`). Relative `memory.path` values resolve from the Artel installation directory; the default repository path is the process's current directory.

Most sections do not reject unknown keys, so a typo can be silently unused. The `prompts` section is strict and rejects unknown fields, profiles, stages, and malformed values. Startup validation is not a complete JSON schema check.

```bash
python3 jira_to_gigacode.py config/team.json --check
python3 jira_to_gigacode.py config/team.json --dry-run
```

`--check` checks the working clone, origin/base branches, CLI availability, and enabled integrations, including live read requests to Jira/Bitbucket/Jenkins. It does not execute a task, but it needs network access and credentials. `--dry-run` shows selection and intended actions without generation, pushes, deployments, Jira transitions, or comments; it still reads the configured systems. Validate the whole enabled installation with `python3 artel.py check`.

### Launch-only environment variables

| Variable | Meaning |
|---|---|
| `CONFIG_PATH` | Config path for a single daemon; an explicit positional path takes precedence. The fallback is `config/config.json`, then the legacy root `config.json`. |
| `ENV_FILE` | Alternative to the installation's `tmp/.env`. |
| `DRY_RUN` | Enable the dry-run mode; `--dry-run` also enables it. |
| `ARTEL_STOP_TIMEOUT` | Supervisor stop timeout, default 120 seconds. This is not the managed updater's wait-for-tasks policy. |

`ARTEL_RESTORE_ACTIVE` and `ARTEL_SUPERVISED` are internal launch variables. Dashboard host, port, assets, and control mode are separate [server options](DASHBOARD.en.md), not daemon JSON keys. Managed update options are documented in [Update guide](../UPDATE.en.md).

## Minimal developer configuration

This is a complete JSON document for `config/team.json`. Replace the example URL, project, statuses, path, and branch with values from your installation. Provide `TEAM_JIRA_TOKEN` through the environment or `tmp/.env`; no token belongs in the public example.

```json
{
  "jira": {
    "url": "https://jira.example.com",
    "project": "TEAM",
    "status_analysis": ["Ready for Development"],
    "status_ready": ["Code Review"]
  },
  "general": {
    "name": "Developer",
    "repo_path": "/work/team-service",
    "base_branch": "main",
    "base_branch_create_from": "main",
    "require_success_marker": true
  },
  "jenkins": {"enabled": false},
  "explore": {"statuses": ["To Do"]}
}
```

This selects all eligible tasks in project `TEAM` in the implementation status. It does **not** restrict tasks by assignee, epic, or configuration item. Add those filters below when needed. Backlog exploration uses `To Do`, which also supplies a return status for `BLOCKED`. Review, bounded memory, automatic memory verification, and scheduled retrospectives retain their built-in defaults; Bitbucket feedback handling remains disabled until configured.

Install the [executor subagent](../subagents/README.en.md) and prepare OpenSpec in each working repository. The daemon requires a Git clone with `origin`; GigaCode and Git credentials must work for the OS user running it. A config entry does not install the CLI, subagent, runtime, test dependencies, or repository.

## Jira and task selection

| JSON key | Default | Purpose | Environment variable |
|---|---|---|---|
| `jira.enabled` | `true` | Enable Jira task acquisition and Jira-dependent work. | `JIRA_ENABLED` |
| `jira.url` | unset | Jira base URL; required when Jira is enabled. | `JIRA_URL` |
| `jira.token` | unset | Bearer token; required when Jira is enabled. | `JIRA_TOKEN` |
| `jira.project` | unset | Required JSON project and identity prefix. The environment override changes request scope only. | `JIRA_PROJECT` |
| `jira.status_analysis` | `[]` | Statuses from which ordinary implementation tasks may be selected; required when enabled. | `JIRA_STATUS_ANALYSIS` |
| `jira.status_ready` | `[]` | Allowed target status names after successful delivery; required when enabled. Actual workflow transitions must exist. | `JIRA_STATUS_READY` |
| `jira.epic_name` | `""` | Value for the optional epic filter. It is effective only with `epic_link_field`. | `JIRA_EPIC_NAME` |
| `jira.epic_link_field` | `""` | Jira field name used by the epic filter, for example `Epic Link`. | `JIRA_EPIC_LINK_FIELD` |
| `jira.ci_field` | unset | Numeric custom-field ID, for example `12345`, used as `cf[12345]` with `general.ci_id`. | `JIRA_CI_FIELD` |
| `jira.assignee` | unset | Optional implementation-task assignee filter. Does not limit backlog exploration. | `JIRA_ASSIGNEE` |
| `jira.result_comments` | `true` | Publish reports, dependency waits, clarification questions, and operator-decision notices in Jira. | `JIRA_RESULT_COMMENTS` |

Implementation JQL includes project and implementation statuses, plus the optional epic, CI, and assignee filters. All result pages are read. Setting only one epic field does not narrow the search; both are needed. The CI filter likewise needs both `jira.ci_field` and `general.ci_id`.

Idle backlog exploration always includes the configured project and, when available, the CI filter. It deliberately omits epic and assignee filters. Without CI configuration it can examine the whole project's configured backlog statuses. There is no general-purpose `jira.jql` setting.

For example, merge this fragment into the corresponding sections of a complete config:

```json
{
  "jira": {
    "epic_name": "Automation",
    "epic_link_field": "Epic Link",
    "ci_field": "12345",
    "assignee": "automation-user"
  },
  "general": {"ci_id": "CI00042"}
}
```

The resulting implementation selection includes `cf[12345] = "42"`; verify that your Jira field accepts the normalized value. `jira.result_comments: false` suppresses notices but does not remove the underlying wait, retry approval, or dependency condition.

Jira uses Artel's Python REST client, not model-side MCP. The current Jira client disables TLS certificate and hostname verification and has no JSON CA/verification option. Its HTTP timeout and retry policy are code-level settings, not `jira.*` fields.

## Repository and execution

| JSON key | Default | Purpose | Environment variable |
|---|---|---|---|
| `general.enabled` | enabled | Only literal JSON `false` excludes the config from supervisor discovery. Direct single-daemon invocation is separate. | — |
| `general.name` | unset | Display name; a dashboard name takes precedence in the UI. | `DAEMON_NAME` |
| `general.ci_id` | unset | Configuration-item identifier and normalized instance identity; JSON only. | — |
| `general.repo_path` | current process directory | Working clone for single-repository mode. Prefer an explicit absolute path. | `REPO_PATH` |
| `general.base_branch` | `develop` | Ordinary task base on `origin` and the branch used when returning the clone after work. | `BASE_BRANCH` |
| `general.base_branch_create_from` | `master` | Starting point for a missing base branch explicitly requested in a Jira comment. | `BASE_BRANCH_CREATE_FROM` |
| `general.branch_prefix` | `feature/ai_team` | Ordinary task branch name is `<prefix>/<ISSUE-KEY>`. Rework uses its recorded branch. | `BRANCH_PREFIX` |
| `general.poll_interval_seconds` | `600` | Delay between daemon polling passes, in seconds. Actual background timing also depends on work already running. | `POLL_INTERVAL` |
| `general.retry_cooldown_seconds` | `3600` | Cooldown after two consecutive technical failures for a task. | `RETRY_COOLDOWN_SECONDS` |
| `general.gigacode_path` | `gigacode` | Executable name or path; not a command plus arguments. | `GIGACODE_PATH` |
| `general.gigacode_timeout_seconds` | `3600` | Timeout of main generation and review-driven rework, in seconds. | `GIGACODE_TIMEOUT` |
| `general.require_success_marker` | `false` | Require `CODE_GENERATION_SUCCESS` as the explicit final success signal; recommended `true`. | `REQUIRE_SUCCESS_MARKER` |
| `general.temp_files` | built-in patterns | Temporary-file patterns excluded from delivery; a nonempty list replaces the defaults. | `TEMP_FILES` |
| `general.compare_url` | unset | Diff URL template using `{branch}`, `{base}` without `origin/`, and `{issue}`. | `COMPARE_URL` |
| `general.service` | unset | Single-repository service name for memory and grouping; routing supplies `services[].name` in multi-service mode. | — |
| `general.role` | inferred | `backend`, `frontend`, or `other` for dependency checks. This is distinct from the prompt profile. | — |
| `general.office_group` | `general.service` | Stable initial office group within a project; rooms hold up to 10 seats. Dashboard assignment is separate. | — |
| `general.character` | automatic | Character asset ID; dashboard selection takes precedence. | — |
| `general.tokens_regex` | unset | Custom regular expression for token counts in CLI output. | `GIGACODE_TOKENS_REGEX` |
| `general.gigacode_chats_dir` | detected CLI chat locations | One path or JSON array of chat directories; environment accepts one path. | `GIGACODE_CHATS_DIR` |

The built-in temporary patterns are `.gigacode`, `.gigacode/*`, `tmp*.py`, `*_tmp.py`, and `tmp_*.py`. An empty `temp_files: []` restores this set rather than disabling exclusions.

There is no supported `general.extra_args` or `general.model` key. Configure the main model using GigaCode's installed settings. Stage-specific CLI arguments are supported in `review`, `explore`, `retro`, `bitbucket`, and memory verification as documented below.

### Branch variants

| Repository convention | `general.base_branch` | `general.base_branch_create_from` |
|---|---|---|
| All work starts from `main` | `main` | `main` |
| All work starts from `master` | `master` | `master` |
| Normal work from `develop`, new named release bases from `master` | `develop` | `master` |

These are branch names on `origin`; `origin/main` and `refs/heads/main` are normalized to `main`. Git revision expressions such as `main~1`, detached commit hashes, and tags do not replace an existing origin branch. An explicit supported `branch:` / `ветка:` instruction in a Jira comment takes precedence for that task. If its branch is absent, the creation base is used.

After the pipeline, Artel attempts to check out the configured base and run `git pull --ff-only origin <base>`. If checkout fails, it does not pull into the wrong branch. This is subject to Git/network success and the protection of changes; configuring a branch is not a guarantee that a failed checkout or update can be ignored. See [task lifecycle and branch handling](WORKFLOW.en.md). For multiple repositories, set branch keys directly on each service, not under `services[].general`.

## Feature switches

The dashboard can choose On, Off, or From config for exactly these settings:

| Key | Default | Environment variable | Dependency |
|---|---|---|---|
| `jira.enabled` | `true` | `JIRA_ENABLED` | — |
| `bitbucket.enabled` | `false` | `BITBUCKET_ENABLED` | Bitbucket credentials and repository |
| `memory.enabled` | `true` | `MEMORY_ENABLED` | — |
| `memory.auto_append` | `true` | `MEMORY_AUTO_APPEND` | Memory enabled |
| `memory.auto_verify` | `true` | `MEMORY_AUTO_VERIFY` | Memory enabled |
| `review.enabled` | `true` | `REVIEW_ENABLED` | — |
| `explore.enabled` | `true` | `EXPLORE_ENABLED` | Jira enabled and nonempty `explore.statuses` |
| `explore.learn` | `false` | `EXPLORE_LEARN` | Exploration and memory candidate collection enabled |
| `retro.enabled` | `true` | `RETRO_ENABLED` | Jira enabled |
| `jenkins.enabled` | `true` | `JENKINS_ENABLED` | Jira enabled and deployment label/settings |
| `requirements.enabled` | `true` | `REQUIREMENTS_ENABLED` | Jira enabled |
| `dependencies.enabled` | `true` | `DEPENDENCIES_ENABLED` | Jira enabled |

Turning Jira off does not itself disable independent Bitbucket processing or memory verification. Saved overrides live in `logs/{instance}-features.json` and survive normal updates. Use the UI to restore From config instead of editing an active runtime-state file by hand.

## Prompts and specialization

The top-level `prompts` section controls text supplied to GigaCode for the daemon and **all its services**. It does not execute arbitrary shell scripts or replace the task protocol.

| JSON key | Default | Purpose |
|---|---|---|
| `prompts.profile` | `developer` | `developer`, `testing`, or `custom`. |
| `prompts.subagent` | `jira-to-deploy-orchestrator` | Installed executor name, without `/`; 1–80 characters, beginning with an ASCII letter, then letters/digits/`_`/`-`. |
| `prompts.instructions` | `""` | Shared extra instructions; up to 6000 characters. |
| `prompts.stages.generation` | `""` | Main task implementation and requested requirements rework. |
| `prompts.stages.review` | `""` | Independent code review. |
| `prompts.stages.rework` | `""` | Fixes requested by the independent reviewer. |
| `prompts.stages.explore` | `""` | Idle backlog research. |
| `prompts.stages.pr_review` | `""` | Bitbucket feedback analysis, corrections, and replies. |
| `prompts.stages.retro` | `""` | Retrospective analysis. |
| `prompts.stages.memory` | `""` | Memory candidate verification. |

Every stage text has its own 6000-character limit. Missing fields become defaults. The final input contains profile instructions, common instructions, stage instructions, and then Artel's normal task context and protocol. Empty text does not disable a stage.

`developer` adds no special role instructions. `testing` asks for acceptance scenarios, existing test tooling, boundary and regression coverage, actual test results, and reproducible defects. It forbids weakening checks just to obtain a pass, and asks for `BLOCKED` when essential test context is missing. `custom` relies on your common and stage instructions. These profiles do not alter JQL or create separate queues.

Changing `subagent` selects the executor for main implementation and review-driven rework; it does not replace every specialized background verifier. The named subagent must already be installed for the daemon's OS user and support Artel's completion markers. Choosing a name in JSON or the UI does not create that subagent.

### Testing daemon

This complete config gives a separate Jira project a testing worker. For two workers in one project, use distinct CI IDs and the appropriate `jira.ci_field`, as explained under identity. Keep working clones separate.

```json
{
  "jira": {
    "url": "https://jira.example.com",
    "project": "QUALITY",
    "status_analysis": ["Ready for Testing"],
    "status_ready": ["Test Review"]
  },
  "general": {
    "name": "Quality",
    "repo_path": "/work/quality-service",
    "base_branch": "main",
    "base_branch_create_from": "main",
    "require_success_marker": true,
    "role": "other"
  },
  "prompts": {
    "profile": "testing",
    "instructions": "Separate reproduced defects from unverified assumptions. Report exact checks and results.",
    "stages": {
      "generation": "Add regression coverage for every reproduced defect within the task scope.",
      "review": "Inspect negative scenarios and integration error handling.",
      "explore": "Identify acceptance criteria that cannot yet be tested and missing test data."
    }
  },
  "jenkins": {"enabled": false},
  "explore": {"statuses": ["To Do"]}
}
```

Here `general.role: "other"` means this worker is not automatically treated as frontend/backend for dependency ordering. It does not create the testing behavior; `prompts.profile` does that. The default installed orchestrator is retained.

Prompt UI settings live in `logs/{instance}-prompts.json`. Saving them does not restart a current job, approve a retry, or clear a `BLOCKED` wait. See [the prompt editor guide](PROMPTS.en.md) for drafts, preview, application status, and conflict handling.

## Multiple services

Only the following per-service fields are supported. A nested object under `services[]` is **not** a general-purpose override of the whole config.

| Service field | Behavior |
|---|---|
| `name`, `repo_path` | Both are required for an entry to be recognized. A malformed entry without either is ignored. |
| `labels` | Exact case-insensitive Jira-label matches. Empty or omitted values fall back to built-in markers or the service name. |
| `keywords` | Whole-word matches in the task summary, case-insensitive. Empty or omitted values also fall back. |
| `role` | Explicit `backend`, `frontend`, or `other` for dependency handling. Otherwise role is inferred. |
| `base_branch`, `base_branch_create_from` | Replace the matching general field when present. Use a valid branch string; `null` falls through to resolver defaults, not to the inherited branch. |
| `branch_prefix`, `compare_url` | A nonempty value replaces the general field. An empty string does not clear an inherited value. |
| `jenkins`, `review`, `memory`, `bitbucket` | Shallow merge with that top-level section; each service key replaces the corresponding common key. Arrays are replaced, not concatenated. |

The sections `jira`, `explore`, `retro`, `dependencies`, `requirements`, and `prompts` are daemon-wide. Nesting them in a service has no effect. There are no per-service environment prefixes: `TEAM_BASE_BRANCH` still overrides the base of every service in that daemon.

Routing combines label matches and summary-word matches. Exactly one matching service is required. `WEB: Add button` matches `web`, while `webhook` does not match that whole word. Zero matches or multiple service matches prevent ordinary implementation; Artel asks for a label or task split in Jira and reevaluates when the summary or labels change. Task selection is still constrained by the daemon's Jira scope.

Default marker sets exist for service names `back`, `web`, `front`, and `mobile`; otherwise the service name is the fallback marker. Set explicit labels and keywords when service names are not meaningful task labels. Idle exploration can use the first configured service when routing is unclear; ordinary implementation does not use that fallback.

### Backend and frontend under one configuration item

This complete example routes two repositories under one CI. Supply `TEAM_JIRA_TOKEN` and `TEAM_BITBUCKET_TOKEN` outside JSON. Replace URLs, paths, status names, CI field/value, and Bitbucket repository slugs. The test commands shown assume the corresponding project test setups already exist.

```json
{
  "jira": {
    "url": "https://jira.example.com",
    "project": "TEAM",
    "ci_field": "12345",
    "status_analysis": ["Ready for Development"],
    "status_ready": ["Code Review"]
  },
  "general": {
    "name": "Product team",
    "ci_id": "CI00042",
    "base_branch": "main",
    "base_branch_create_from": "main",
    "require_success_marker": true
  },
  "jenkins": {"enabled": false},
  "explore": {"statuses": ["To Do"]},
  "bitbucket": {
    "enabled": true,
    "url": "https://bitbucket.example.com",
    "project": "TEAM",
    "bot_user": "artel-bot",
    "verify_ssl": true
  },
  "services": [
    {
      "name": "back",
      "role": "backend",
      "repo_path": "/work/product-back",
      "labels": ["backend"],
      "keywords": ["backend"],
      "memory": {"verify_commands": [["./mvnw", "-B", "test"]]},
      "bitbucket": {
        "repo": "product-back",
        "test_commands": [["./mvnw", "-B", "test"]]
      }
    },
    {
      "name": "web",
      "role": "frontend",
      "repo_path": "/work/product-web",
      "labels": ["frontend"],
      "keywords": ["frontend", "web"],
      "memory": {"verify_commands": [["npm", "test", "--", "--runInBand"]]},
      "bitbucket": {
        "repo": "product-web",
        "test_commands": [["npm", "test", "--", "--runInBand"]]
      }
    }
  ]
}
```

Each service inherits the common Bitbucket connection and uses its own repo slug. This example explicitly sets test commands for both memory verification and PR validation; those two command settings are independent. The web test flags are appropriate only for a compatible test runner; replace them with your project's actual noninteractive command.

Memory defaults become `memory/ci42-back.md` and `memory/ci42-web.md`, with structured sidecar files. A custom `memory.path` should include `{key}` if it is meant to preserve this separation. A fixed path can accidentally make several services share one store.

## Linked-task dependencies

| JSON key | Default | Meaning | Environment variable |
|---|---|---|---|
| `dependencies.enabled` | `true` | Check linked-task ordering before registering an attempt. | `DEPENDENCIES_ENABLED` |
| `dependencies.external_ready_label` | `backend-ready` | Exact label required on a frontend task for external-CI backend readiness. ASCII letters/digits/`_`/`-`, up to 100 characters. | `DEPENDENCIES_EXTERNAL_READY_LABEL` |
| `dependencies.ready_statuses` | `jira.status_ready` | Backend ready status names. Explicit `[]` disables readiness by status name. | `DEPENDENCIES_READY_STATUSES` |
| `dependencies.accept_done` | `false` | Also accept Jira's `done` status category. | `DEPENDENCIES_ACCEPT_DONE` |
| `dependencies.allow_code_branch` | `true` | Accept a same-CI backend's Development branch when Git confirms a nonempty diff. | `DEPENDENCIES_ALLOW_CODE_BRANCH` |
| `dependencies.dev_application_type` | `stash` | Development API application type for Bitbucket Server/Data Center. | `DEPENDENCIES_DEV_APPLICATION_TYPE` |
| `dependencies.dev_data_type` | `pullrequest` | Development API data type; `branch` is another supported configuration. | `DEPENDENCIES_DEV_DATA_TYPE` |
| `dependencies.link_types` | `[]` | All Jira link types, or exact type names ignoring case. | `DEPENDENCIES_LINK_TYPES` |
| `dependencies.backend_markers` | `back, backend, бек, бэк, beck, бэкенд, бекенд` | Replacement set of whole-word/label role markers. | `DEPENDENCIES_BACKEND_MARKERS` |
| `dependencies.frontend_markers` | `front, frontend, web, фронт, фронтенд, веб, mobile, ios, android` | Replacement set of frontend markers. | `DEPENDENCIES_FRONTEND_MARKERS` |
| `dependencies.max_links` | `50` | Clamped to 1–100. Too many relevant links block the task rather than silently dropping dependencies. | `DEPENDENCIES_MAX_LINKS` |

Artel reads actual Jira issue links in either direction, not arbitrary URLs in the description. For frontend work within one CI, every linked backend must meet the configured status rule or code-branch rule. A queued or active backend rework request prevents stale status/branch evidence from unlocking the frontend.

For a backend in another CI, a person must put the configured readiness label on the **frontend task**. An external backend's status or branch does not replace this explicit agreement, and the label does not bypass an unfinished same-CI backend. Without enough CI configuration, the related backend is treated as requiring the external readiness label. Ambiguous roles require clarification instead of guessing.

Development readiness checks match the reported repository to the backend clone's `origin`, fetch exact refs, and inspect the diff. A branch merely existing is insufficient. A nonempty diff is a configured readiness signal; it is not evidence that code was merged, deployed, or tested. Unreadable Development metadata leaves the dependency waiting unless the status rule already allows it.

To require ready statuses only, merge this fragment:

```json
{
  "dependencies": {
    "allow_code_branch": false,
    "ready_statuses": ["Code Review", "Ready for QA"],
    "accept_done": true,
    "link_types": ["Blocks", "Relates"]
  }
}
```

These link type names must exist in your Jira installation. Dependency waits do not consume technical retries and do not authorize implementing a linked issue outside normal task scope.

## Independent code review

| JSON key | Default | Meaning | Environment variable |
|---|---|---|---|
| `review.enabled` | `true` | Run an independent review of delivered changes. | `REVIEW_ENABLED` |
| `review.gigacode_path` | main CLI | Optional separate reviewer executable. | `REVIEW_GIGACODE_PATH` |
| `review.extra_args` | `[]` | Additional argument list, for example a reviewer model selection. | `REVIEW_EXTRA_ARGS` |
| `review.prompt_prefix` | `""` | Text prepended to the review prompt, for example invoking an installed reviewer subagent. | `REVIEW_PROMPT_PREFIX` |
| `review.max_rework_rounds` | `1` | Correction rounds in one attempt; minimum 0. | `REVIEW_MAX_REWORK_ROUNDS` |
| `review.block_on_changes` | `true` | Prevent normal completion/deployment when review still requests changes. | `REVIEW_BLOCK_ON_CHANGES` |
| `review.on_no_verdict` | `pass` | `pass` allows continuation without a recognized verdict; `block` stops it. | `REVIEW_ON_NO_VERDICT` |
| `review.timeout_seconds` | `1200` | Timeout for a reviewer CLI invocation. | `REVIEW_TIMEOUT` |
| `review.max_diff_chars` | `40000` | Maximum diff characters included in the review prompt. | `REVIEW_MAX_DIFF_CHARS` |

Review uses an isolated worktree and expects `APPROVE` or `REQUEST_CHANGES`. It happens after pushing the task branch; blocking delivery status does not mean no branch was published. Rework runs with the main executable and main timeout, then review repeats up to the configured limit.

For stricter verdict handling, merge:

```json
{
  "review": {
    "enabled": true,
    "max_rework_rounds": 2,
    "block_on_changes": true,
    "on_no_verdict": "block"
  }
}
```

Use `review.extra_args: ["--model", "model-name"]` only with a model identifier your installed CLI supports. `review.prompt_prefix` and `prompts.stages.review` are model instructions, not shell commands.

## Memory

Memory separates durable operator rules, verified repository knowledge, and untrusted candidate observations. Repetition or a successfully completed task does not itself confirm a lesson. Only applicable confirmed entries and operator rules are supplied as reusable context.

| JSON key | Default | Meaning | Environment variable |
|---|---|---|---|
| `memory.enabled` | `true` | Read/use memory and allow its related functions. | `MEMORY_ENABLED` |
| `memory.auto_append` | `true` | Collect new candidates from completed work. Turning this off does not remove existing entries or stop verification of them. | `MEMORY_AUTO_APPEND` |
| `memory.path` | `memory/{key}.md` | Base path; `{key}` includes normalized instance ID and service suffix. | `MEMORY_PATH` |
| `memory.max_chars` | `6000` | Prompt memory-content budget, excluding its wrapper. | `MEMORY_MAX_CHARS` |
| `memory.max_candidates` | `100` | Candidate cap; rejected entries have a separate cap of the same size. | `MEMORY_MAX_CANDIDATES` |
| `memory.max_confirmed` | `40` | Confirmed-entry cap. | `MEMORY_MAX_CONFIRMED` |
| `memory.candidate_days` | `30` | Retention for candidate and rejected entries. | `MEMORY_CANDIDATE_DAYS` |
| `memory.review_after_days` | `90` | Confirmed knowledge becomes a candidate for re-verification after this age. | `MEMORY_REVIEW_AFTER_DAYS` |
| `memory.history_max_bytes` | `1000000` | Audit-file rotation threshold; minimum 16384 bytes, one rotated file retained. | `MEMORY_HISTORY_MAX_BYTES` |
| `memory.auto_verify` | `true` | Check existing candidates automatically during idle time. | `MEMORY_AUTO_VERIFY` |
| `memory.verify_every_minutes` | `60` | Minimum interval between candidate checks for a store. | `MEMORY_VERIFY_EVERY_MINUTES` |
| `memory.verify_retry_hours` | `24` | Retry delay after a technical error or interrupted verification. | `MEMORY_VERIFY_RETRY_HOURS` |
| `memory.verify_base` | `origin/<base_branch>` | Git ref for the verification worktree. | `MEMORY_VERIFY_BASE` |
| `memory.verify_timeout` | `300` | Timeout of each of the two verifier CLI calls. | `MEMORY_VERIFY_TIMEOUT` |
| `memory.verify_test_timeout` | `300` | Timeout per actual test command. | `MEMORY_VERIFY_TEST_TIMEOUT` |
| `memory.verify_commands` | automatic detection | JSON array of argv arrays; first five commands are used. | JSON only |
| `memory.verify_gigacode_path` | main CLI | Optional verifier executable. | `MEMORY_VERIFY_GIGACODE_PATH` |
| `memory.verify_extra_args` | `[]` | Verifier CLI arguments. | `MEMORY_VERIFY_EXTRA_ARGS` |

Memory counts, ages, prompt budget, and verification intervals are clamped to at least 1. Use the booleans to disable behavior. The caps bound structured knowledge, not every file in the installation. A legacy `.md` is retained; the current store, rules, and audit live beside it as `.store.json`, `.rules.md`, and `.history.jsonl`, with one `.history.jsonl.1` archive. Operator rules and task-history files have different lifecycles.

The model proposes evidence; Python checks exact citations against committed code and runs the configured tests itself. A structural fact can be confirmed by direct code evidence. Behavioral claims need relevant executed tests. Ambiguous or insufficiently evidenced candidates remain for review in the Memory screen. A worktree isolates repository files, not OS permissions.

### Test commands are argument arrays

This fragment explicitly permits two commands in the temporary verification worktree:

```json
{
  "memory": {
    "verify_commands": [
      ["python3", "-m", "unittest", "discover", "-s", "tests"],
      ["npm", "test", "--", "--runInBand"]
    ]
  }
}
```

Use only commands appropriate to that repository and OS. Commands must be nonempty arrays of nonempty strings. `"npm test && npm run lint"` is not a supported command representation. Shell expansion, pipes, redirection, `$VARIABLE`, and `&&` are not interpreted for you. Configure separate argv arrays or an existing script executable when necessary. The configured binaries and dependencies must already be available; Artel does not install them automatically.

Omitted or `null` `memory.verify_commands` triggers detection in this order:

| Detected repository | Command family |
|---|---|
| `pom.xml` | Maven wrapper if present, otherwise Maven: `-B test` |
| `build.gradle` / `build.gradle.kts` | Gradle wrapper if present, otherwise Gradle: `test --no-daemon` |
| `package.json` with `scripts.test` | `pnpm test` with pnpm lockfile, otherwise `yarn test` with yarn lockfile, otherwise `npm test` |
| `go.mod` | `go test ./...` |
| `Cargo.toml` | `cargo test` |
| `tests/` | Current Python executable with pytest if configuration is detected, otherwise `unittest discover -s tests` |
| None of these | No automatically selected tests |

Windows uses the appropriate `.cmd`/`.bat` wrappers for detected Maven, Gradle, and package-manager commands. Explicit commands are your responsibility. An explicit `[]` disables automatic test selection: structural memory facts may still be verified, but behavioral claims cannot be confirmed without tests.

For a daemon that uses existing knowledge but collects no new lessons, set `memory.auto_append: false`. To stop background verification as well, also set `memory.auto_verify: false`; leave `memory.enabled: true` to keep reading applicable memory. Set `memory.enabled: false` to disable memory use entirely.

## Bitbucket Server and Data Center

This integration is for self-hosted Bitbucket Server/Data Center, not Bitbucket Cloud. It uses a Python REST client, independently of GigaCode MCP connectivity. It finds open PRs for work recorded as delivered by Artel; enabling it does not ask the daemon to process every PR in the server.

| JSON key | Default | Meaning | Environment variable |
|---|---|---|---|
| `bitbucket.enabled` | `false` | Enable idle PR-feedback handling. | `BITBUCKET_ENABLED` |
| `bitbucket.url` | unset | HTTPS base URL without embedded credentials, query, or fragment. | `BITBUCKET_URL` |
| `bitbucket.project` | unset | Bitbucket project key, independent of Jira project. | `BITBUCKET_PROJECT` |
| `bitbucket.repo` | unset | Repository slug. | `BITBUCKET_REPO` |
| `bitbucket.token` | unset | Bearer personal access token. | `BITBUCKET_TOKEN` |
| `bitbucket.bot_user` | unset | Login identifying Artel's reply author. | `BITBUCKET_BOT_USER` |
| `bitbucket.verify_ssl` | `false`, or `true` when a CA file is provided | Certificate and hostname verification. Explicit `false` still disables it even with `ca_file`. | `BITBUCKET_VERIFY_SSL` |
| `bitbucket.ca_file` | unset | Optional trusted CA PEM path; enables verification if `verify_ssl` is not explicitly set. | `BITBUCKET_CA_FILE` |
| `bitbucket.http_timeout` | `30` | Per-HTTP-request timeout in seconds, minimum 1. | `BITBUCKET_HTTP_TIMEOUT` |
| `bitbucket.poll_interval_seconds` | `600` | Minimum background poll interval, clamped to at least 60 seconds. | `BITBUCKET_POLL_INTERVAL` |
| `bitbucket.batch_comments` | `true` | Process new feedback together for one PR, with separate replies to individual discussions. | `BITBUCKET_BATCH_COMMENTS` |
| `bitbucket.max_per_cycle` | `1` | PR quota per service and pass; in non-batch mode, discussion quota. Minimum 1. | `BITBUCKET_MAX_PER_CYCLE` |
| `bitbucket.max_tasks_per_cycle` | `20` | Delivered-task records scanned for PRs per pass, round-robin. Minimum 1. | `BITBUCKET_MAX_TASKS_PER_CYCLE` |
| `bitbucket.max_age_days` | `90` | Maximum delivered-record age considered for PR discovery. Minimum 1. | `BITBUCKET_MAX_AGE_DAYS` |
| `bitbucket.gigacode_path` | main CLI | Executor for PR analysis, corrections, and rechecks. | `BITBUCKET_GIGACODE_PATH` |
| `bitbucket.extra_args` | `[]` | Additional CLI arguments. | `BITBUCKET_EXTRA_ARGS` |
| `bitbucket.timeout_seconds` | `1200` | Per-CLI-call timeout, minimum 1 second. | `BITBUCKET_TIMEOUT` |
| `bitbucket.test_commands` | automatic detection | JSON argv arrays; first five are used. An explicit `[]` prevents automatic correction pushes. | JSON only |
| `bitbucket.test_timeout` | `300` | Per-test-command timeout, minimum 1 second. | `BITBUCKET_TEST_TIMEOUT` |

All of `url`, `project`, `repo`, `token`, and `bot_user` are required when enabled; a service can supply its own repo. Git access for fetching and pushing is separate from the REST token. Background polls run when the daemon reaches idle work, so the interval is not an independent exact schedule.

`batch_comments: true` gathers new actionable feedback for the selected PR into one analysis/fix pass and then replies separately to the handled discussions. It does not repost answers to unchanged comments already completed, or silently retry ambiguous sends. Reasoned objections undergo an independent check. Disputed decisions and uncertain `sending` records require attention; Jira notices expose that state when result comments are enabled.

PR corrections need actual configured/detected tests before automatic push. If `bitbucket.test_commands` is absent or `null`, the code uses the same detection algorithm described for memory verification, independently of `memory.verify_commands`. Setting memory commands does not configure PR tests. To require a particular PR validation command, explicitly set `bitbucket.test_commands`.

### TLS variants

The following are fragments to merge into a complete enabled Bitbucket section:

| Desired behavior | Fragment |
|---|---|
| Current Jira-like default, no custom certificate file and no certificate/hostname checks | `{"bitbucket": {"verify_ssl": false}}` |
| Verify with the OS trust store, without a custom file | `{"bitbucket": {"verify_ssl": true}}` |
| Verify with a specific corporate CA bundle | `{"bitbucket": {"verify_ssl": true, "ca_file": "/etc/company-ca.pem"}}` |

The first variant still uses HTTPS encryption but does not authenticate the server certificate. For a server trusted by the OS, `verify_ssl: true` is sufficient; no CA path is needed. A nonexistent CA file with verification enabled makes initialization fail rather than falling back silently.

## Backlog exploration

| JSON key | Default | Meaning | Environment variable |
|---|---|---|---|
| `explore.enabled` | `true` | Permit idle research; statuses and Jira must also be enabled. | `EXPLORE_ENABLED` |
| `explore.statuses` | `[]` | Backlog statuses to explore and target statuses for returning `BLOCKED` tasks. | `EXPLORE_STATUSES` |
| `explore.prompt_template` | built-in `/opsx:explore …` prompt | Optional text template with `{key}`, `{summary}`, `{description}`, `{project}`, `{repo}`, `{base}`, and `{memory}`. | `EXPLORE_PROMPT_TEMPLATE` |
| `explore.base` | `origin/<base_branch>` | Git ref for the isolated exploration worktree. | `EXPLORE_BASE` |
| `explore.max_per_cycle` | `1` | Maximum stories examined in one idle pass; minimum 1. | `EXPLORE_MAX_PER_CYCLE` |
| `explore.max_scan` | `200` | Backlog records scanned per pass to find eligible work; minimum 1. | `EXPLORE_MAX_SCAN` |
| `explore.min_hours_between` | `336` | Minimum interval between explorations of the same issue; values below 336 are raised to 336 (14 days). | `EXPLORE_MIN_HOURS` |
| `explore.reexplore_on_update` | `true` | Revisit a previously explored issue when its requirements/discussion changed and the interval has elapsed. | `EXPLORE_REEXPLORE` |
| `explore.learn` | `false` | Collect memory candidates from exploration, subject to memory switches. | `EXPLORE_LEARN` |
| `explore.timeout_seconds` | `900` | Exploration CLI timeout. | `EXPLORE_TIMEOUT` |
| `explore.gigacode_path` | main CLI | Optional explorer executable. | `EXPLORE_GIGACODE_PATH` |
| `explore.extra_args` | `[]` | Extra explorer arguments. | `EXPLORE_EXTRA_ARGS` |

The 14-day lower bound is **per issue**, not a global limit of one suggestion for the entire daemon every two weeks. Previously explored stories are reconsidered on a changed content fingerprint; the daemon edits its existing exploration comment. Its own report edits do not count as a new analyst clarification. If a legacy record has no fingerprint, a baseline is established rather than treating every timestamp change as new requirements.

An empty status list prevents exploration and leaves `BLOCKED` tasks without an automatic return-status target. Setting only `explore.enabled: false` stops research, while a populated `explore.statuses` can still provide blocked-return statuses. Exploration publishes its own proposal comments independently of `jira.result_comments`; use `explore.enabled: false` to stop that work. A custom `prompt_template` is text for GigaCode, not a shell script; preserve the expected read-only exploration behavior. Its named placeholders are replaced literally, so ordinary braces elsewhere do not need doubling.

## Retrospectives

| JSON key | Default | Meaning | Environment variable |
|---|---|---|---|
| `retro.enabled` | `true` | Enable scheduled retrospective processing. | `RETRO_ENABLED` |
| `retro.window` | `01:00-05:00` | Local-time window on the daemon machine; can cross midnight, such as `23:00-03:00`. | `RETRO_WINDOW` |
| `retro.every_days` | `7` | Minimum interval between runs; minimum 1 day. | `RETRO_EVERY_DAYS` |
| `retro.min_age_days` | `2` | Minimum age of delivered work to inspect. | `RETRO_MIN_AGE_DAYS` |
| `retro.max_age_days` | `30` | Maximum age while waiting to establish the delivered task's outcome/merge. | `RETRO_MAX_AGE_DAYS` |
| `retro.max_tasks` | `10` | Task quota, oldest first; minimum 1. | `RETRO_MAX_TASKS` |
| `retro.timeout_seconds` | `1800` | Retrospective CLI timeout. | `RETRO_TIMEOUT` |
| `retro.max_diff_chars` | `12000` | Diff budget per task. | `RETRO_MAX_DIFF_CHARS` |
| `retro.gigacode_path` | main CLI | Optional separate retrospective executable. | `RETRO_GIGACODE_PATH` |
| `retro.extra_args` | `[]` | Additional CLI arguments. | `RETRO_EXTRA_ARGS` |

This is a background window, not a promise of execution at an exact clock time: ordinary work and the daemon loop take precedence. The interval calculation includes a six-hour allowance to keep weekly runs within the night window. Configure the machine's timezone appropriately; there is no `retro.timezone` key. Identical window endpoints produce an empty window, not a full day. An unparseable window falls back to 01:00–05:00. To request a retrospective immediately, use `python3 jira_to_gigacode.py config/team.json --retro`; adding `--dry-run` only shows the facts without carrying out the analysis. See [memory and retrospectives](MEMORY.en.md).

## Jenkins

| JSON key | Default | Meaning | Environment variable |
|---|---|---|---|
| `jenkins.enabled` | `true` | Permit deployment triggered by a task's Jenkins label. | `JENKINS_ENABLED` |
| `jenkins.url` | `""` | Jenkins base URL. | `JENKINS_URL` |
| `jenkins.user` | `""` | API user. | `JENKINS_USER` |
| `jenkins.token` | `""` | User API token. | `JENKINS_TOKEN` |
| `jenkins.job_name` | `""` | Job path, including folders when needed. | `JENKINS_JOB` |

Deployment requires the appropriate `jenkins_<environment>[_migration]` issue label and complete settings. The job parameter names `refName`, `filter`, and `MIGRATION`, and the built-in mapping of environment labels, are defined in `jira_gigacode/jenkins.py`; there are no JSON keys to rename them. A common URL/user/token can be combined with per-service `job_name` overrides. An environment `JENKINS_JOB` overrides all those jobs, so avoid it when services need different ones.

## Retries, BLOCKED, and rework

These behaviors share state but are different operations:

| Situation | What happens | Relevant configuration/control |
|---|---|---|
| Two technical failures | A persisted cooldown delays another ordinary attempt. | `general.retry_cooldown_seconds`; the failure threshold of two is not configurable. |
| Wrong task or unwanted repeat | Exclude it, pause it for an hour, or explicitly allow a retry. | Dashboard **Retries** or `artel.py retry`; no `retry.enabled` section. |
| Restart after interruption or changed scope/behavior | An old attempt can require explicit approval. | Current config/prompt scope and retry ledger. |
| Executor returns `CODE_GENERATION_BLOCKED` | Persist a clarification wait, publish its question, attempt a transition to a configured backlog status. | `explore.statuses`, `jira.result_comments`; not a technical failure retry. |
| Analyst changes an already delivered task | Queue an explicit requirements rework request with a reason; separate analytics record it. | `requirements.enabled`, then dashboard request. |
| Code delivered but Jira transition failed | Retain the pending transition instead of generating the task again. | Persisted pending-transition ledger. |

`requirements.enabled` defaults to `true` and has environment variable `REQUIREMENTS_ENABLED`. It is the only public key in that section. The issue key, new requirements, and rework reason are submitted through the dashboard, not hidden config fields.

For `BLOCKED`, Artel resumes when the relevant requirements or human discussion fingerprint changes and the task still passes current project/CI/epic/assignee scope, routing, dependency, and operator controls. A lack of workflow transition leaves the issue in place with an explanatory notice; it does not turn the blocker into repeated technical attempts. The ordinary wait does not require a manual retry approval, but a changed config scope can add that requirement.

```bash
python3 artel.py retry list team
python3 artel.py retry block team TEAM-123
python3 artel.py retry pause team TEAM-123
python3 artel.py retry resume team TEAM-123
```

Use the instance ID (`team` or `ci42`), not the display name. A retry approval never bypasses current task selection. A comment in Jira does not substitute for a required explicit retry approval; this differs from answering a `BLOCKED` clarification. Actions control the next attempt and do not interrupt the current one.

Retry, blocked, notification, PR, and pending-transition records live under `logs/` and are preserved by managed updates. Do not delete this directory to clear an issue: it also holds analytics and the records that prevent duplicated delivery or uncertain replies. See [Runbook](RUNBOOK.en.md) for recovery.

## Logs and token usage

| JSON key | Default | Meaning | Environment variable |
|---|---|---|---|
| `logs.max_mb` | `20` | Rotate eligible text logs after this many MiB; `0` disables size rotation. Negative values become 0. | `LOG_MAX_MB` |
| `logs.cli_keep_days` | `14` | Age before CLI logs in the system temporary directory are moved to the archive; `0` disables age-based archival. Negative values become 0. | `LOG_CLI_KEEP_DAYS` |

Archives are gzip files under `logs/archive/YYYY-MM/` and are retained indefinitely. Rotation is not deletion or a total disk quota. Task history (`*-history.jsonl`) and delivered-task journals (`*-delivered.jsonl`) are not archived by this policy because analytics and subsequent work use them. Starting a new CLI run for a task also archives a previous run's log rather than overwriting it, independently of age-based cleanup.

GigaCode event output is exposed in the daemon's live log view as events arrive. `general.tokens_regex` and `general.gigacode_chats_dir` customize token accounting, not log-stream transport. A custom regex must contain a first capturing group for the numeric total; the last matching occurrence is used. JSON needs escaped backslashes, for example `"tokens_regex": "Total tokens: ([0-9]+)"`. An invalid regex or missing capture group is not a useful fallback. Detected chat roots include `.gigacode`, `.qwen`, and `.gemini` under the home directory, preferring the working repository's project subdirectory when available. No `logs.stream_enabled` or similar setting is required. See [Operations](OPERATIONS.en.md) for paths, manual archiving, and process logs.

## Environment and Windows examples

Keep credentials in the process environment or the installation's `tmp/.env`, which is excluded from Git. The file format is `KEY=VALUE`, one variable per line; full-line `#` comments are supported and outer quotes are removed. It is not a shell script, so do not use `export`, command substitution, or expect variable interpolation.

For JSON project `TEAM`, nonsecret overrides could be:

```dotenv
TEAM_BASE_BRANCH=main
TEAM_BASE_BRANCH_CREATE_FROM=main
TEAM_REVIEW_ON_NO_VERDICT=block
TEAM_EXPLORE_STATUSES=To Do,Backlog
TEAM_BITBUCKET_VERIFY_SSL=true
```

Set the real `TEAM_JIRA_TOKEN` and, if needed, `TEAM_BITBUCKET_TOKEN` in that private file or the process environment. Do not copy secrets into a published config. For a second JSON project `QUALITY`, use `QUALITY_JIRA_TOKEN`; for two CIs inside `TEAM`, `TEAM_*` still applies to both. To give same-project processes different environment values, launch them with separate environments/`ENV_FILE` paths rather than inventing a CI-prefixed setting.

The example above intentionally uses base-branch environment overrides for a single-repository installation. Remove them if different services need different JSON branch values. The same caveat applies to `REPO_PATH`, `JENKINS_JOB`, `COMPARE_URL`, `BRANCH_PREFIX`, and any common environment setting overriding a supported per-service field.

PowerShell launch example, using a separately prepared private environment file:

```powershell
$env:ENV_FILE = "C:/artel-private/team.env"
py -3 -X utf8 jira_to_gigacode.py config/team.json --check
py -3 -X utf8 artel.py up
```

Windows-specific JSON fragment to merge into the single-repository config:

```json
{
  "general": {
    "repo_path": "C:/work/team-service",
    "gigacode_path": "gigacode.cmd"
  },
  "memory": {
    "verify_commands": [["py", "-3", "-m", "unittest", "discover", "-s", "tests"]]
  },
  "bitbucket": {
    "test_commands": [["npm.cmd", "test", "--", "--runInBand"]]
  }
}
```

Use the actual GigaCode executable exposed by your installation; it may not be named `gigacode.cmd`. The test examples illustrate argv syntax, not a requirement to combine Python and JavaScript in every service. Linux/macOS commonly use `python3`, `npm`, `./mvnw`, and `./gradlew`; Windows explicit commands commonly use `py`, `npm.cmd`, `mvnw.cmd`, and `gradlew.bat`.

## Applying a change safely

1. Edit only the intended daemon JSON or private environment file. Confirm its instance ID and working clone.
2. Run `--check`, then inspect `--dry-run` selection when changing project, statuses, epic, CI, assignee, routing, or branches.
3. Restart the affected daemon to load JSON/environment changes. For jobs already running, choose the appropriate stop/update workflow rather than assuming a config edit changes them in place.
4. Review persisted dashboard overrides if a JSON value appears to have no effect. Prompt and feature UI changes have separate application status.
5. Inspect pending retries, blockers, and rework requests before authorizing another attempt under changed behavior.

For dashboard/server arguments, see [Dashboard](DASHBOARD.en.md). For managed updates that back up data, wait for work, replace code, and restore processes, see [Update guide](../UPDATE.en.md). Those controls are intentionally outside the daemon configuration described here.
