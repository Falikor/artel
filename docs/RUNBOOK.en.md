# Runbook: when intervention is needed

[English](RUNBOOK.en.md) · [Русский](RUNBOOK.md) · [Home](../README.md) · [Configuration](CONFIGURATION.en.md) · [Processes and logs](OPERATIONS.en.md)

Run commands from the Artel directory. On Windows, replace `python3` with `py -3 -X utf8`.
In `restart`, `team` is the filename `config/team.json` without its extension. In `retry`/`pr`,
`ID` is the instance identifier found in `logs/`, such as `ci42` or `team`, not the character's
display name.

## A task appears stuck

1. Open the daemon's **GigaCode logs** and **Daemon log** tabs. Check the latest tool, error,
   and event timestamp. A lack of new lines alone does not prove a hang: a tool may be running
   a long command.
2. Run `python3 artel.py status`. If the daemon is running, compare elapsed time with the
   current stage's timeout: `general.gigacode_timeout_seconds`, `review.timeout_seconds`,
   `bitbucket.timeout_seconds`, or `memory.verify_timeout`.
3. If the agent needs an answer, check the Jira comment and the waiting states below.
   Do not increase retries for a task whose requirements are incomplete.
4. To interrupt execution, select **Stop** in daemon settings. This interrupts the CLI.
   After checking the result, start the daemon and approve a retry in **Retries** if needed.
   To stop the whole service, run `python3 artel.py down`.

Recovery preserves interrupted commits under `refs/ai-team-interrupted/…`. Do not delete retry
history or Git refs to “unblock” a task. If code has already been published, check the branch
and PR first: a pending Jira transition does not require generating the code again.

## The daemon does not pick up a task

Check these conditions in order. Requesting an immediate Jira check does not bypass them.

1. **Process and configuration.** Run `python3 artel.py status`, then
   `python3 jira_to_gigacode.py config/team.json --check`. The file must end in `.json`,
   `general.enabled` must not be `false` for supervisor startup, and Jira must be enabled in
   the daemon panel.
2. **Search scope.** Check the project, `jira.status_analysis`, epic, CI, and assignee.
   `jira.assignee` limits ordinary task selection, but not backlog exploration. Preview selection
   without implementation: `python3 jira_to_gigacode.py config/team.json --dry-run`.
3. **Routing.** With `services[]`, the summary and labels must identify exactly one service.
   If zero or multiple services match, fix the markers; the daemon explains the reason in Jira.
4. **Dependencies.** Frontend work in the same CI waits for a ready backend status or a verified
   branch containing code in Development. A backend in another CI requires the agreed
   `backend-ready` label on the frontend issue. See the [detailed rules](WORKFLOW.en.md).
5. **Retries.** Open **Retries**: the task may be excluded, paused, in cooldown, or awaiting
   approval after an interruption or configuration change.
6. **Working clone.** Check the log: a dirty working tree, an unavailable origin branch, Git
   access, or the CLI may block execution. Preserve your own changes through your normal workflow.

After correcting the configuration, run `python3 artel.py restart team`, then select
**Settings → Check Jira now**. Backlog exploration also requires `explore.enabled` and a
nonempty `explore.statuses` list.

## Removing a pause or approving a retry

In the daemon panel, open **Retries**, select the task, and allow the retry. CLI equivalent:

```bash
python3 artel.py retry list ID
python3 artel.py retry resume ID TEAM-123
```

`resume` removes this task's exclusion/pause and cooldown and approves the next attempt.
Current JQL, routing, and dependencies still apply. This is not a command to execute any issue
by key. For changed requirements on a completed task, use **Rework**.

If the daemon itself is stopped, select **Start** first or run `python3 artel.py restart team`.
**Pause scene** pauses animation only and does not affect execution. Enable a disabled feature
under **Settings → Daemon features**. **Use configuration** returns control to JSON and ENV.
A new choice applies at a safe boundary, not in the middle of the current task.

## BLOCKED: the agent needs an answer

`CODE_GENERATION_BLOCKED` is a separate waiting outcome, not a technical failure that triggers
retries. The daemon publishes the subagent's question in Jira and tries to return the issue
to one of `explore.statuses` using an available direct transition. If no such transition exists,
the task remains waiting with an explanation. Correct its status manually or fix the
configuration without deleting daemon state.

Reply in Jira or clarify the summary/description. The daemon returns after the requirements
or a human comment change; its own messages and a simple status change do not trigger a retry.
There is no 14-day interval for this waiting state. Current project, CI, assignee, routing,
dependencies, and manual exclusions are still checked. Requested rework keeps its separate
queue and analytics.

## Bitbucket: disputed feedback or `sending`

`sending` means the outcome of a POST is unknown: the reply may already exist on the server.
Open the PR and inspect the discussion before taking action. Do not manually post the same
reply again until you have established that the first one is absent.

```bash
python3 artel.py pr list ID
python3 artel.py pr retry ID RECORD_ID
python3 artel.py pr skip ID RECORD_ID
```

`RECORD_ID` is the complete record ID from `list`. `retry` first reconciles the prepared send
with the server. `skip` completes processing of that discussion version without posting a
message. For disputed feedback, `retry` allows a new assessment. See the
[detailed procedure](BITBUCKET.en.md).

## Decisions requiring the operator appear in Jira

Retry approval requests, disputed PR findings, and uncertain `sending` outcomes are published
in the Jira issue with a reason, a PR/discussion link, and the next action. Repeated states
update the daemon's existing comment instead of creating duplicates. A new Jira reply alone
does not authorize a risky retry: use the panel or the specified CLI command. For BLOCKED,
the reply serves as a requirements clarification, as described above.

These messages require both `jira.enabled` and `jira.result_comments`. If Jira or result comments
are disabled, use the panel and CLI. The notification queue is persisted in
`logs/{ID}-notifications.json`. A Jira read/edit error does not lose the decision; after an
uncertain POST, the daemon first looks for its own reply instead of blindly sending it again.

## The old interface remains, or daemons are missing after an update

1. Open the HTTP address of the running dashboard, not `output/Artel_Interactive.html`, which
   is a presentation.
2. Check the package with the updater's `--verify-only` and the correct `--target`, then refresh
   the page. `--assets`/`OFFICE_ASSETS` may point to an older external sprite pack.
3. Compare versions using `python3 artel.py status`. Restart outdated daemons with
   `python3 artel.py restart --outdated`.
4. If cards are missing, check that `--logs` points to the active daemons' logs. Starting a
   different installation copy creates a different set of logs.

If the port is occupied, use `artel.py down` when the dashboard was started by `up`; otherwise,
stop it using its original launch method. To use a different port, run
`python3 artel.py up --port 8766`. Do not terminate an unknown process merely because it owns
that port.

## Corrupted JSON or an update failure

Stop the affected process, preserve a copy of the corrupted file, and restore it from an
appropriate backup. Do not replace damaged state with empty JSON: you could lose task
exclusions, posted replies, or knowledge. The updater preserves data and can roll back code;
see the [recovery procedure](../UPDATE.en.md#errors-and-recovery).
