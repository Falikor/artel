# Task lifecycle

**English** · [Русский](WORKFLOW.md)

[Home](../README.md) · [Configuration](CONFIGURATION.en.md) · [Runbook](RUNBOOK.en.md)

## An ordinary task

The daemon finds tasks in `jira.status_analysis` and checks search scope, service, dependencies, and retry authorization. It prepares a branch, passes the task to GigaCode, publishes changes, runs independent review, and requests rework if needed. A Jenkins label triggers deployment; the daemon transitions the issue to `jira.status_ready` and updates its report comment. Idle work includes [PR checks](BITBUCKET.en.md), [backlog exploration](BACKLOG.en.md), and [memory processing](MEMORY.en.md).

## BLOCKED: waiting for clarification

When the main executor or rework executor finishes with `CODE_GENERATION_BLOCKED`, the result is recorded separately from a technical error. The question between `BLOCKED_QUESTION_START` / `BLOCKED_QUESTION_END` is published in Jira; for older output formats, the available blocker explanation is used. The daemon does not mark the task complete, automatically retry it, or consume the technical-failure cooldown.

The issue returns directly to the first available status in `explore.statuses`. This is independent of `explore.enabled`. If the list is empty, the transition is unavailable, or Jira returns an error, execution remains blocked and the notice states the required action. The daemon does not move the issue through arbitrary intermediate statuses.

Work can resume after the title, description, or human comments change. A status change alone, or Artel's own comments, does not restart execution. The 14-day backlog-exploration interval does not apply here. Reselection uses the current project, epic, CI, assignee, service routing, dependencies, and manual exclusions; configured implementation statuses and waiting statuses from `explore.statuses` are allowed.

State lives in `logs/{instance}-blocked.json` and survives restarts. Unfinished work resumes with its saved branch and base; a clarification does not automatically create a new branch over a different set of requirements.

A manual rework request that returns BLOCKED remains a separate request: after clarification it returns to its own queue, and its time and outcome continue to be accounted for separately from ordinary tasks.

## Rework after requirements change

If an analyst changes the requirements of an already completed task:

1. Update the issue description in Jira.
2. In the selected daemon's panel choose **New requirements**, or open **Rework → New rework request**.
3. Select the daemon, enter the issue key, and briefly explain what changed.
4. The request is saved in the queue. The daemon takes it after its current work, before the next ordinary task.

The daemon obtains the current title and description through Jira REST, independently of MCP. A manual request does not depend on the current Jira status, but is allowed only within the selected daemon's project; existing routing rules determine its service. Exclusions and pauses in retry controls are not bypassed. If configuration changes after a request is queued, a new request is required. Unavailable Jira, an oversized description, or a dirty working repository prevents the run from starting.

Each request gets its own `<branch_prefix>/<KEY>-requirements-<request-id>` branch. If the previous work is not merged, the base is the current tip of its remote branch, including human edits. If it is merged or its branch is gone, the current `general.base_branch` is used. The previous branch and PR are not overwritten. Create a separate PR for the new branch if needed.

After generation, the daemon checks the description again: if it changed or Jira cannot be reached, publication stops. Otherwise normal review, Jenkins-by-label, Jira transition, and report-comment update follow.

The **Rework** screen separately shows the queue, outcomes, stop reasons, duration, tokens, branch, and fingerprint of the received requirements. It supports period, office, and daemon filters plus search. Time and tokens exclude queue waiting; unknown usage is marked unknown. Rework is excluded from ordinary task statistics and the card's success/failure task counters. Retrospectives continue to show the latest delivery of a task.

A waiting request can be cancelled. A failure, stop, or restart during execution **does not trigger an automatic retry**: inspect the result and create a **New request**. That is a separate attempt with a new branch. BLOCKED is the exception: it waits for clarification in Jira and returns to the queue when the requirements change. To interrupt a running request, use the normal daemon stop control.

Ordinary retries of that issue after rework begins require a separate operator decision in retry controls, so an older attempt cannot overwrite the new work.

Queue and outcomes: `logs/{instance}-requirements.json`. Completed rework is also written to `*-history.jsonl` with `request`. Preserve all of `logs/` during updates; the existing updater already retains this data. No new config parameters are required. Requests cannot be submitted in demo mode, while viewing another logs directory, or with `--no-control`.

## Base branch

For a repository using `main`, put these fields inside `general`:

```json
{"base_branch": "main", "base_branch_create_from": "main"}
```

`base_branch` is used for tasks without an explicit base in a Jira comment, returning the clone after work, and as the default base for backlog exploration and memory verification. `explore.base` and `memory.verify_base` can independently override background-check bases; they accept a Git ref such as `origin/release/1.0`. Retrospectives use the base recorded when the particular task was delivered.

The latest user marker `branch: release/1.0` or `ветка: release/1.0` in Jira comments takes precedence over `general.base_branch`; the daemon ignores its own reports. If the named branch is absent from origin, the daemon publishes an existing local branch with that name. If no local branch exists either, it creates one from `base_branch_create_from` and publishes it. A missing branch **from the config** is not automatically created: correct the name or create it first. Without these settings, the previous defaults of `develop` and `master` remain.

Both fields accept a name (`main`, `release/1.0`), `origin/main`, or `refs/heads/main`; the remote is always `origin`. Revisions such as `main~1`, commit SHAs, and tags do not replace an existing origin branch. For a service, put the same keys directly inside `services[]`, not under a nested `general`. `general.branch_prefix` is a different setting: it names the resulting task branch, for example `feature/ai_team/HRPPA-123`.

Templates: [single repository](../config/example.json.sample) and [multiple services](../config/example-services.json.sample). The supervisor does not launch `.sample` files. Copy the chosen template to `.json`, replace addresses, paths, and statuses, and configure tokens.

## Several services under one CI: backend and frontend

If a CI contains several repositories, list them in `services` instead of using one `general.repo_path`. Merge this fragment into the daemon config; routing markers are retained exactly as in the Russian example:

```json
{
  "services": [
    {"name": "back", "role": "backend", "repo_path": "/work/hr-back",
     "keywords": ["бек", "бэк", "beck", "back", "backend", "бэкенд"], "labels": ["back", "backend"],
     "jenkins": {"job_name": "hr/deploy-back"}},
    {"name": "web", "role": "frontend", "repo_path": "/work/hr-web",
     "keywords": ["web", "веб", "фронт", "front", "frontend"], "labels": ["web", "front"],
     "jenkins": {"job_name": "hr/deploy-web"},
     "compare_url": "https://bitbucket.example.com/projects/HR/repos/hr-web/compare/diff?sourceBranch={branch}&targetBranch={base}"}
  ]
}
```

**How service settings combine with common settings:**

| Setting | Present in the service | Absent from the service |
|---|---|---|
| `name`, `repo_path` | Required: service name and clone path | The entry is ignored without them |
| `labels`, `keywords` | Arrays of routing markers | Built-in markers based on the service name |
| `role` | Task role: `backend`, `frontend`, or `other` | Inferred from service name, labels, and words in the task title |
| `base_branch`, `base_branch_create_from`, `branch_prefix`, `compare_url` | Override the matching common `general` setting | Inherit the common setting |
| `jenkins`, `review`, `memory`, `bitbucket` | **Merge** with the common section: service keys win, other keys remain common | Inherit the entire common section |

Typically the common `jenkins` section holds `url` and `user`, with the token in `tmp/.env`, and each service supplies only `job_name`. **Environment variables override both common and service settings:** `REPO_PATH`, `JENKINS_JOB`, `COMPARE_URL`, `BRANCH_PREFIX`, `BASE_BRANCH`, and `BASE_BRANCH_CREATE_FROM`, including project-prefixed versions such as `HRPPA_JENKINS_JOB`, would give every service the same value. Startup checks warn about these overrides.

Routing uses **labels** (exact, case-insensitive matches) and **title words** (whole words, such as `[Бек] Добавить поле` or `WEB: кнопка`; `webhook` does not match `web`):

- Exactly one matching service: the daemon works in that repository with its Jenkins job.
- No matching service, or several matches: the daemon **does not take the task** and posts one comment explaining recognized labels/words or asking to split the task. Once the title or labels change, routing is checked again and work can start if the service is unambiguous.

Other sections inside `services[]` do not override common settings; only the fields listed above are supported. See [the precise merge and empty-value rules](CONFIGURATION.en.md#multiple-services).

Every service has separate memory: `memory/{instance}-{service}.md`. Without `keywords`/`labels`, service names `back`, `web`, `front`, and `mobile` have built-in marker sets; other names use the service name itself. Backlog exploration uses the task's service repository, or the first service if routing is unclear. `--dry-run` shows which service a task would use.

## Linked tasks: backend before frontend

Before starting GigaCode, the Python daemon reads `issuelinks` and linked issue fields through Jira REST. URLs in free text do not replace actual Jira issue links. Both directions of a link are considered; backend/frontend roles determine ordering. All link types are considered by default. `dependencies.link_types` can restrict them, for example to `Blocks` and `Relates`.

- **Same CI:** linked backend tasks precede the frontend task. Frontend work is allowed when every linked backend has reached `jira.status_ready` **or** its **Development** panel contains a branch whose changes are confirmed in Git. A backend must have no queued or active rework request: an old status or branch does not override that request.
- **Different CIs:** the **frontend task** requires the **`backend-ready`** label. A person adds it after agreeing that the external backend is ready. The daemon does not add it; the external backend's status or branch does not replace this permission. A label on the backend issue is not permission.
- **Several dependencies:** all conditions must hold. `backend-ready` does not bypass an unfinished backend in the same CI.
- **Missing CI configuration or ambiguous roles:** the daemon does not guess. Without `jira.ci_field` and `general.ci_id`, a linked backend requires external `backend-ready` permission. Clarify ambiguous roles using labels or configuration. A configured service with role `other` does not use backend/frontend ordering. A linked issue in another CI must expose its role through its title or labels.

CI membership is checked with additional JQL for specific issue keys and the same `cf[...]` used for task selection; the internal Assets/custom-field representation is not guessed. Main search retains project, epic, CI, status, and assignee filters and reads every page. Dependencies are filtered **after the REST response and before registering an attempt**, so waiting frontend tasks do not hide a backend on page two or consume retries. Linked tasks outside the main search scope are read only for context; the daemon does not start implementing them without ordinary eligibility.

The waiting reason appears in one comment owned by the daemon. Conditions changing cause the comment to be edited; when the wait ends, it is updated again. If Jira comments cannot be read, no new duplicate is created and the reason remains in the log. `jira.result_comments=false` disables these notices but not dependency checks. While all tasks wait on dependencies or operator decisions, normal background PR checks, memory checks, and retrospectives continue.

### Development branch evidence

The check uses `/rest/dev-status/1.0/issue/detail`, the numeric issue ID, `applicationType=stash`, and `dataType=pullrequest`. This is an internal Jira Data Center interface described by [Atlassian](https://support.atlassian.com/jira/kb/how-to-retrieve-pull-request-and-bitbucket-repo-and-branch-information-from-an-issue-using-rest-api/). The token needs permission to view the issue and Development, and the Application Link must supply Bitbucket details. If your version exposes branches only with `dataType=branch`, change the setting below. An incomplete response, access error, or unknown format leaves the frontend waiting. Once `status_ready` is reached, Development access is unnecessary.

The repository reported by Development is matched to the backend service's `origin`. The daemon then fetches the exact branch and base into separate temporary Git refs and checks for a nonempty diff from their common ancestor. It does not switch working files or branches, and does not push. A deleted branch, a branch from another repository, or a branch without changes does not unlock work.

The existence of changes **does not mean** the code is merged, deployed, or tested: it is a separate readiness criterion authorized by the operator. The corresponding backend service needs an accessible clone and correct base branch.

The subagent receives linked issue keys and URLs, roles, statuses, descriptions, and the verified branch. Each linked description is limited to 2,000 characters, with a total budget of 12,000. If the contract is insufficient, the executor must report a blocker. It implements only the assigned task, does not modify linked issues, and does not add its own permission label.

Merge this fragment into the daemon config:

```json
{
  "dependencies": {
    "enabled": true,
    "external_ready_label": "backend-ready",
    "allow_code_branch": true,
    "dev_application_type": "stash",
    "dev_data_type": "pullrequest"
  }
}
```

[All settings for this feature](CONFIGURATION.en.md#linked-task-dependencies).

Markers match whole title words and full labels. `backend-ready` is not a backend-role marker. Explicit `services[].role` takes precedence. Otherwise known service names `back`, `backend`, `web`, `front`, `frontend`, and `mobile` determine the service role. In single-repository mode you can set `general.role`. Dependency settings are daemon-wide and cannot be overridden per service.

Manual rework from the dashboard goes through the same eligibility check. While a dependency is not ready, its request stays queued with **Waiting for a dependency**, can be cancelled, and does not prevent backend execution. `--dry-run` shows the reason without writing comments or launching GigaCode.

Local tests do not exercise the corporate Development API or real GigaCode.

## Executor subagent

The supplied [jira-to-deploy-orchestrator](../subagents/jira-to-deploy-orchestrator.en.md) performs OpenSpec `propose → apply → checks → sync → archive`, leaving push, Jenkins, and Jira to the daemon. See [installation and completion protocol](../subagents/README.en.md).

`general.require_success_marker: true` is recommended: a successful response must end with a separate `CODE_GENERATION_SUCCESS` line. Explicit `CODE_GENERATION_BLOCKED` / `CODE_GENERATION_FAILED` and a nonzero CLI exit code are not accepted as success even when changes exist. The subagent definition is installed separately from Artel's code; the updater delivers only the template.

## Independent review

After push, a separate GigaCode run in a **temporary checkout** (`git worktree`) reads the diff and code and returns `APPROVE` or `REQUEST_CHANGES` with feedback. When changes are requested, the agent reworks the branch up to `max_rework_rounds` times and review runs again. If feedback remains, the task is not transitioned or deployed; a comment lists the feedback, and the next attempt receives it in its prompt.

[All review settings](CONFIGURATION.en.md#independent-code-review).

## Retry controls

Expand **Retries** in the daemon panel. You can exclude an issue by key even before its first attempt, pause it for an hour, or allow another attempt while resetting cooldown. The decision belongs to one daemon and is checked before an attempt starts. These buttons do not interrupt current work; stopping the daemon is a separate action.

An interrupted attempt, or a retry after configuration/JQL scope changes, requires explicit permission. Configuration checking is conservative: changes to any parameter can require confirmation. An approved issue must still match current JQL and service routing. The control does not launch an arbitrary task outside the filters. For a new configuration, restart the daemon and then approve the required retries.

The cooldown after two errors survives restarts. The journal and decisions live in `logs/{ID}-retries.json` and are preserved by code updates. A corrupted file blocks attempts until repaired instead of resetting to an empty queue. Older unfinished Jira transitions require confirmation. The “code already delivered, only the Jira transition remains” marker no longer expires after a day, so a long pause does not rerun generation.

From the terminal (`ID` is the daemon file prefix in logs, not its display name):

```bash
python3 artel.py retry list hrppa
python3 artel.py retry block hrppa HRPPA-123
python3 artel.py retry pause hrppa HRPPA-123
python3 artel.py retry resume hrppa HRPPA-123
```

`pause` pauses for an hour; `resume` permits the next attempt within current selection rules. A dashboard started with `--no-control` is read-only. Older versions that did not record attempts cannot reconstruct the exact prior configuration; exclude an unwanted task by its key.

A required retry confirmation is also published in Jira with its reason and requested action. A human comment does not replace explicit approval in **Retries** or `artel.py retry resume`. This differs from BLOCKED, which specifically waits for clarification of the requirements.

## Issue comments

The daemon reports implementation results (branch, review, deployment, status, time, and tokens), failed review with feedback, cases where code is ready but the Jira transition needs help, inability to implement after two consecutive failures, and backlog suggestions. Tokens and passwords in error messages are replaced with `***`.

Operator decisions and BLOCKED have separate persistent notices: when the reason changes, the existing comment is updated. Disable reports and notices with `"jira": {"result_comments": false}`; the decision wait still applies. Backlog exploration has its own comment publication path, controlled by exploration settings; see [the configuration reference](CONFIGURATION.en.md#backlog-exploration).
