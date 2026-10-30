# Daemon behavior and prompts

**English** · [Русский](PROMPTS.md)

[Home](../README.md) · [Configuration](CONFIGURATION.en.md) · [Dashboard](DASHBOARD.en.md)

The **Prompts** tab configures an individual role, common instructions, instructions for each stage, and the executor subagent's name. Settings apply to the selected daemon and all its services. Other daemons retain their own settings.

## Configure through the dashboard

1. Open **Prompts** and choose a daemon. Configured daemons that have not started yet also appear in the list.
2. Choose **Developer**, **Tester**, or **Custom role**.
3. If necessary, change the installed subagent name and the common instructions.
4. Select a stage and add instructions specific to it. Switching stages retains the draft.
5. Select **Preview instructions**, check the text, and then **Save**.

Preview shows the customizable part of the prompt. It does not run GigaCode or change settings. Artel adds the task requirements, repository context, and mandatory rules during an actual run.

**From config** prepares a return to the JSON config's `prompts` section; select **Save** to apply it. If that section is absent, the default developer with `jira-to-deploy-orchestrator` is restored. **Discard changes** removes only the unsaved draft. Drafts survive daemon and tab switching within the current browser page; reloading the page does not retain them. Conflicting changes from two tabs do not silently overwrite data: the editor offers to reconcile the server version while preserving the draft.

## Profiles and stages

| Profile | Behavior |
|---|---|
| `developer` — Developer | Artel's standard workflow; no additional profile instructions |
| `testing` — Tester | Derives testable scenarios from acceptance criteria, examines the existing test stack, and adds/runs automated tests for main behavior, boundaries, and regressions |
| `custom` — Custom role | Specialization comes from common and stage-specific instructions |

The tester must not weaken checks to obtain a successful result. It changes product code when that is part of the task; otherwise it describes a reproducible defect. The report must include the checks actually performed and their results. If an essential scenario cannot be verified without more data or an environment, it uses the existing `BLOCKED` protocol. A profile does not change JQL or create a separate testing queue: Jira configuration and service routing still determine task selection.

| Stage key | Where the instructions are added |
|---|---|
| `generation` | Main task execution and manual rework for changed requirements |
| `review` | Independent code review |
| `rework` | Corrections requested by the independent reviewer |
| `explore` | Idle backlog exploration |
| `pr_review` | Bitbucket feedback analysis, corrections, and replies |
| `retro` | Retrospective analysis of delivered work and lesson extraction |
| `memory` | Memory candidate verification against code and tests |

Each request begins with profile instructions, common instructions, and the selected stage text. Artel's standard prompt follows. An empty field does not cancel a stage or remove its normal instructions. Custom text does not replace the rules for branches, access, verification, publication, or `SUCCESS` / `BLOCKED` markers.

## Prompt versus terminal command

The editor stores **text for the model**, passed to the existing GigaCode CLI through stdin. It is not a shell-script editor: added lines are not executed directly by a shell. The CLI path, actual test commands, schedules, and feature switches remain separate [settings](CONFIGURATION.en.md).

**Executor subagent** contains a name without `/`, for example `jira-to-deploy-orchestrator`. It is used for task implementation and rework after review. The specified subagent must already be installed in GigaCode for the user running the daemon; renaming the field does not create a subagent file. See [executor installation](../subagents/README.en.md). A custom subagent must support Artel's mandatory completion protocol.

## JSON configuration example

Merge this fragment at the top level of the selected daemon's config. The example retains its Russian model instructions; keys and behavior are the same regardless of dashboard language.

```json
{
  "prompts": {
    "profile": "testing",
    "subagent": "jira-to-deploy-orchestrator",
    "instructions": "В отчёте отделяй подтверждённые дефекты от непроверенных предположений.",
    "stages": {
      "generation": "Добавляй регрессионный тест для каждого воспроизведённого дефекта.",
      "review": "Проверь негативные сценарии и обработку ошибок интеграций.",
      "explore": "Ищи непроверяемые критерии приёмки и отсутствующие тестовые данные."
    }
  }
}
```

The common instruction asks the worker to separate confirmed defects from unverified assumptions. The generation instruction asks for a regression test for each reproduced defect; the review instruction focuses on negative scenarios and integration error handling; the exploration instruction looks for untestable acceptance criteria and missing test data. You can write these model instructions in the language appropriate to your team.

All fields are optional; omitted stages receive empty text. Common instructions and each stage have a separate **6,000-character** limit. There are no environment equivalents or per-service `services[].prompts`. Unknown fields, profiles, and stages are rejected.

## When settings take effect

Saved UI settings take precedence over the config's `prompts` section. They are written atomically to `logs/{instance}-prompts.json` and survive restarts and normal updates. Editing the JSON config requires a daemon restart; saving through the UI does not.

The current task or background operation finishes with the instructions it started with. New instructions apply before the next work item. The tab shows whether settings have been applied, are waiting for work to finish, or await the daemon's next start.

Behavior changes participate in retry-context checks. A previously started task must not automatically continue with a new profile: that retry requires confirmation. Saving instructions alone does not remove a task exclusion, a pause, or a `BLOCKED` wait.

In demo mode, you can edit a draft and preview it, but saving is disabled. `--no-control` and viewing another logs directory also prevent settings changes. A corrupted prompt file stops new work from being acquired rather than silently reverting to default behavior.
