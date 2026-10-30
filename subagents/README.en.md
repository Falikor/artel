# Artel task executor for GigaCode CLI

**English** · [Русский](README.md)

Ready-to-install definition: [jira-to-deploy-orchestrator.md](jira-to-deploy-orchestrator.md).
An [English translation of the definition](jira-to-deploy-orchestrator.en.md) is also available as an optional standalone copy. It preserves the original agent name, tools, completion markers, and requirement to report in Russian. It does not replace the installed or default definition automatically. The format is Markdown with YAML frontmatter; the name matches Artel's invocations.

## Install on the mini

1. Back up the existing `jira-to-deploy-orchestrator.md`, if one is installed.
2. Place the new definition at `~/.gigacode/agents/jira-to-deploy-orchestrator.md` **under the OS user who runs the daemons**. This is the shared executor for that user's repositories. Alternatively, install it in `.gigacode/agents/` inside every service's working repository. A project definition takes precedence over the user definition, so check that an older project file does not shadow the new one. If using the optional English copy, install its contents under the same canonical filename; do not install two definitions with the same agent name.
3. In every working repository, check the installed OpenSpec version, project initialization, and availability of the propose, apply, sync, and archive workflows. The agent does not automatically install tools. Follow the instructions for your OpenSpec version; slash commands are not shell commands.
4. Open GigaCode CLI in the working repository and check the agent using `/agents manage`. Run a trial task in a test repository with a local origin, not a production project.
5. For the strict protocol, set `"general": {"require_success_marker": true}` in the daemon config, adding the key to the existing section. Restart the daemons after updating Artel and the agent definition.

`update_artel.py` delivers the `subagents/` directory into the Artel installation. It **does not overwrite** definitions in the home directory or working repositories: install the file there separately. Real GigaCode CLI and corporate projects on the mini were not exercised during local development.

For the optional English definition, after backing up any installed file, run this from the Artel directory on Linux/macOS:

```bash
mkdir -p ~/.gigacode/agents
cp subagents/jira-to-deploy-orchestrator.en.md ~/.gigacode/agents/jira-to-deploy-orchestrator.md
```

The source has `.en.md`; the installed destination keeps the canonical `.md` filename. Choose one language version for each installation location, not both.

## What the agent does

Reads the supplied task and checks the working branch → creates or continues an OpenSpec change → implements it → runs applicable checks → synchronizes specifications → archives the completed change → returns a report and final text signal.

Assistant commands are commonly `/opsx:propose`, `/opsx:apply`, `/opsx:sync`, and `/opsx:archive`. Exact names depend on the OpenSpec integration. If slash commands are unavailable inside the subagent, it reads the installed instruction for the corresponding workflow and follows its steps. If those instructions are unavailable too, it returns a blocker. Autonomous execution does not cancel approvals explicitly required by project rules.

Push, independent review, deployment, and Jira transitions remain the daemon's responsibility. The agent does not receive MCP tools through its allowlist; shell is allowed for Git, OpenSpec, builds, and tests. Textual restrictions **do not replace** OS permissions, process isolation, or network restrictions.

## Result protocol

The last nonempty line of the parent's final response must be one of:

- `CODE_GENERATION_SUCCESS` — implementation, checks, and the applicable OpenSpec cycle are complete;
- `CODE_GENERATION_BLOCKED` — access, a tool, clarification, or another external action is needed;
- `CODE_GENERATION_FAILED` — execution failed.

These are result strings, not terminal commands. A LESSONS block appears before them and only when requested. The parent must carry the subagent's result into its own final response.

For BLOCKED, put the question for the operator between separate `BLOCKED_QUESTION_START` and `BLOCKED_QUESTION_END` lines before the final signal. State the missing fact or action that would allow work to continue. The parent must preserve this block in its final response. Do not include secrets, a complete tool log, or unsupported claims.

A nonzero CLI exit code and an explicit standalone BLOCKED/FAILED signal prevent continuation regardless of partially written code. Success requires a separate final nonempty signal line. Compatibility mode (`require_success_marker: false`) may still accept exit code 0 without a signal when work exists; strict mode is recommended for this executor. The same rules apply to rework after review.

A marker is a model assertion, not proof that OpenSpec completed: Python does not validate archive completeness or the truth of the test report. Keep independent review enabled. FAILED remains a technical failure. BLOCKED is a separate wait: the daemon publishes the question in Jira, attempts to return the issue to a configured backlog status, and waits for requirements or human discussion to change instead of automatically retrying. [Detailed workflow](../docs/WORKFLOW.en.md#blocked-waiting-for-clarification).

## Check before using it for real work

In a test repository, check four cases: a successful task with an archive and final signal; missing OpenSpec; a failing mandatory check; and rework of an already archived change after review. The last two must not produce false success or rewrite an old archive. Verify that the agent does not push or call Jenkins/Jira. If the installed CLI rejects the allowlist, check its available tool names.

Format and workflow references: [GigaCode CLI subagents](https://gitverse.ru/docs/ai/ai-assistant-gigacode/gigacode-cli/subagents) and [official OpenSpec OPSX](https://github.com/Fission-AI/OpenSpec/blob/main/docs/opsx.md).
