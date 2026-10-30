# Handling Bitbucket feedback

**English** · [Русский](BITBUCKET.md)

[Home](../README.md) · [Configuration](CONFIGURATION.en.md) · [Runbook](RUNBOOK.en.md)

## Pull request feedback during idle time

Artel can revisit PRs for its delivered tasks: read human feedback, fix substantiated issues, and reply with reasoned objections to unsupported requests. The integration supports **Bitbucket Server / Data Center**, not Bitbucket Cloud. Python handles network operations: REST for PR discovery, discussions, and replies; Git for publishing code. The PR handler's allowed tools include only local file tools and shell, without MCP. Its operation does not depend on Jira/Bitbucket MCP connections in GigaCode. GigaCode receives the task through the existing Jira REST client, the discussion text, and a temporary code checkout.

Merge this section into the daemon config:

```json
{
  "bitbucket": {
    "enabled": true,
    "url": "https://bitbucket.example.com",
    "project": "HR",
    "repo": "backend",
    "bot_user": "artel-bot",
    "batch_comments": true,
    "poll_interval_seconds": 600,
    "max_per_cycle": 1,
    "test_commands": [["./mvnw", "-B", "test"]]
  }
}
```

Set `BITBUCKET_TOKEN=…` or `<JIRA_PROJECT>_BITBUCKET_TOKEN=…` in `tmp/.env`. The technical account needs permission to read PRs and write comments. `bot_user` is its exact login (`name`/`slug`), not its display name. Configure Git push access separately in the working clone.

`url` is the root HTTPS address, including a context path if present. By default, Bitbucket behaves like the existing Jira REST client: HTTPS without certificate or hostname verification, with no certificate file required. This encrypts the connection but does not authenticate the server. For verification using system CAs, set `verify_ssl: true`; for a custom CA, use `ca_file`. If `ca_file` is already set, verification defaults to enabled. Explicit `verify_ssl: false` disables verification and ignores `ca_file`. Redirects to login pages are not accepted. These settings apply to Bitbucket REST; Git fetch/push use Git/SSH settings.

After configuring it, run `python3 jira_to_gigacode.py config/hrppa.json --check` and restart the daemon.

## Which PRs are selected

Only open PRs for the exact source branch recorded in `*-delivered.jsonl` are considered, within the configured repository and service. The branch must contain the commit delivered by the daemon. Both fetch and push addresses for `origin` must match one of the repository's Bitbucket clone URLs. Fork PRs, closed PRs, and tasks without a delivery record are not processed automatically.

The check runs when ordinary Jira search finds no implementation work, before the other background activities. Tasks waiting on dependencies or operator decisions should not prevent these background checks; the daemon panel shows the reason for waiting.

## Decisions on feedback

By default, `batch_comments: true` supplies all new open feedback for the selected PR in one pass, including nested replies, with the full discussion context. For each ID, the agent chooses a correction, an objection, or referral to the operator.

All justified corrections are made in one executor call, with shared tests, independent review, and one commit/push. Python then sends a **separate reply to each handled comment** describing its specific result, rather than posting one general PR report. Python validates links and quotations. Objections are checked by a separate model call and, if a shared correction is made, checked again against the final code.

With the default settings, `max_per_cycle: 1` means one PR with all its comments, not one comment. Set `batch_comments: false` for the earlier discussion-by-discussion mode; the quota then counts discussions again.

Ambiguous requirements and objections that cannot be substantiated are stored in the journal and published in the linked Jira issue for an operator decision, with the reason, discussion link, and exact command. Artel skips its own replies and closed discussions. A new human reply or an edit to human text allows the decision to be reconsidered. Tracking survives normal restarts. Discussions handled before an upgrade are not processed again unless a new reply appears.

A large batch is not silently truncated: the context limit is 240,000 JSON characters per PR and 24,000 JSON characters per discussion. Processing is deferred with a journal reason if the limit is exceeded.

## Corrections

The executor works in a temporary detached checkout of the current PR branch. Python executes the test commands, commits the verified changes, runs a separate diff review, and performs a normal push to the source branch without `--force`. Without test commands, there is no automatic push. Files created only during tests are not included in the commit.

If the branch, target revision, or discussion changes during processing, publication is deferred. A “fixed” reply is sent only after confirming that the new commit is present in the PR. The daemon does not resolve discussions, merge the PR, run Jenkins, or transition the Jira issue again. Server-side CI hooks on push follow Bitbucket's rules.

## Failures and controls

Task exclusions, pauses, and required operator decisions from retry controls also apply here and are checked again before publication. A technical error triggers a one-hour pause. The journal stores the prepared commit before push, so a failure after publication does not require generating the changes again.

Replies include a tracking marker for reconciliation. If a POST has an uncertain outcome, the daemon looks for the marker in the discussion rather than blindly sending the reply again. A `sending` state without a matching reply requires the operator to check. The same request appears in Jira with the record ID used by the CLI.

If one reply fails, the remaining prepared replies in the batch continue sending. An unfinished batch is reconciled with the server first; a new commit is not generated for it. While uncertain sends remain, the next batch for that PR waits for an operator decision.

```bash
python3 artel.py pr list hrppa
python3 artel.py pr retry hrppa ID
python3 artel.py pr skip hrppa ID
```

`ID` is the full identifier from `list`. These commands change local state only. `retry` permits another assessment of disputed feedback; for `prepared`/`sending`, it retains the prepared result and reconciles it with the server first. Before retrying `sending`, check whether the reply already appeared. `skip` finishes processing that version of the discussion without sending a message. If configuration or the branch changed after preparation, inspect the saved commit and error before taking another action.

The dashboard shows the review/rework stage and log; it does not yet have a dedicated PR list.

Notices for comments on the same PR are combined into one Artel-owned Jira comment and updated when state changes. They respect `jira.enabled` and `jira.result_comments`. With Jira disabled, the journal and CLI remain available. The delivery queue lives in `logs/{instance}-notifications.json`. Text in Jira alone does not approve another send.

[All settings for this feature](CONFIGURATION.en.md#bitbucket-server-and-data-center).

## Services and persisted state

Each `services[]` entry can supply its own `bitbucket` section, merged with the common section. Environment variables override both levels: a common `BITBUCKET_REPO` replaces the repository for every service.

State is stored in `logs/<instance>-pr-review-<identifier>.json`, with a lock file beside it. Completed and disputed records are trimmed when the journal exceeds 1,000 records; unresolved publications are retained. Prepared commits are protected by `refs/artel-pr-review/*` references in the repository. The updater preserves the journal with the other logs.

A temporary Git checkout isolates working files, not process permissions. Prompt restrictions are not a sandbox. A second model call can also be wrong: verified quotations and tests reduce risk, but do not prove every objection correct. Test the real connection to your corporate Bitbucket version after configuring the mini.

REST contract: [Atlassian: retrieving PR comments](https://support.atlassian.com/bitbucket-data-center/kb/how-to-retrieve-pull-request-comments-using-rest-api/) and [Pull Requests API reference](https://developer.atlassian.com/server/bitbucket/rest/v1000/api-group-pull-requests/).
