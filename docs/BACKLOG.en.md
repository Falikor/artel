# Backlog exploration

**English** · [Русский](BACKLOG.md)

[Home](../README.md) · [Configuration](CONFIGURATION.en.md) · [Runbook](RUNBOOK.en.md)

## Exploring the backlog while idle

When there are no implementation tasks, the daemon searches the backlog **within its own Jira project, configuration item (CI), and statuses**, without epic or assignee filters. Recently updated issues come first:

```text
project=<jira.project> AND cf[<jira.ci_field>] = "<CI>" AND status IN ("TO DO", "Backlog") ORDER BY updated DESC
```

Without CI configuration (`jira.ci_field` + `general.ci_id`), the query is `project=<jira.project> AND status IN (…)`; startup checks warn about this broader scope. Results are read in pages of 50 until an unexplored task is found, up to `explore.max_scan`. The daemon then runs GigaCode with `/opsx:explore` in a temporary repository copy, without changing the working repository. The result appears as a Jira comment: questions about requirements, affected code, approaches and risks, acceptance criteria, and a complexity estimate.

An issue is explored again when its title, description, or human discussion changes after the previous exploration. Comment additions, edits, and deletions count. Changes only to status or labels, and Artel's own reports, do not count as new requirements. A repeat suggestion is published no more often than once every 14 days; a longer configured interval is respected. This interval applies separately to each issue and survives daemon restarts.

On a repeat exploration, the daemon edits its previous comment instead of adding another. The author is checked against the current Jira account, and ownership by the daemon is checked against its instance marker. For older comments, the heading and daemon name are used. If duplicates already exist, the latest is updated; older comments are not deleted. A read or edit failure does not create a new duplicate. The Jira account needs permission to edit its own comments.

The daemon obtains the discussion through REST and passes it to the explorer together with the current requirements. A content fingerprint and the daemon's comment ID are saved in `logs/{instance}-explored.json`. If an older journal lacks a fingerprint, or the journal was lost, the daemon records the current requirements once without publishing again: it cannot reliably reconstruct the previous text. Subsequent changes are tracked normally. Preserve `logs/` when moving an installation.

[All settings for this feature](CONFIGURATION.en.md#backlog-exploration).

For example, to use your own subagent instead of OpenSpec, set `prompt_template` as follows. This example retains the Russian model instructions; the command, placeholders, and output markers must remain intact:

```json
{
  "prompt_template": "вызови суб агента /explorer изучи задачу {key}: {summary}\n{description}\nИтог выведи между EXPLORE_START и EXPLORE_END"
}
```

Merge this fragment into the `explore` section; it is not a complete daemon config.
Its instruction means: invoke the `/explorer` subagent to study issue `{key}`, its `{summary}` and `{description}`, and return the result between `EXPLORE_START` and `EXPLORE_END`.
