# Artel dashboard

[Русский](DASHBOARD.md) · **English**

[Home](../README.md) · [Configuration](CONFIGURATION.en.md) · [Runbook](RUNBOOK.en.md)

## Dashboard sections

The **Русский / English** selector sits beside the theme selector. The language is saved
locally in your browser and applies to every section, form, tooltip, control message,
office dialogue, and CSV export. Changing the language reloads the page; unsaved changes
trigger a confirmation first. Names, task requirements, custom instructions, memory
entries, and original logs remain in their original language. The interface language
does not change GigaCode instructions or the language of Jira messages.

- **Team:** buildings, offices, and daemons. Search by name, office, or task and filter by
  state; select a daemon card to open its logs and controls.
- **Prompts:** each daemon's role, subagent, general instructions, and instructions for
  seven stages. Includes a tester profile and a preview that does not start GigaCode.
  See [Behavior settings](PROMPTS.en.md).
- **Rework:** a queue for tasks whose requirements have changed, with separate time and
  token accounting. Create requests in the inline form; cancelling a queued request
  requires confirmation.
- **Statistics:** task and attempt history, charts, token prices, and CSV export.
- **Analytics:** task and attempt counts, failed attempts, first-attempt completions,
  median and P90 total task duration, tokens, and estimated cost; compare daemons and
  services. Cost and token metrics show measurement coverage. Unknown prices do not
  mean zero cost. The period selects tasks by their latest completion and includes all
  of those tasks' attempts.
- **Retrospectives:** one row for each daemon's latest delivery of a task: merged
  unchanged, merged with edits, branch deleted without merging, still open, awaiting
  review, or unknown outcome. Shows human commits and changed lines, follow-up work,
  check date, branch, commit, and Jira status. The period uses the delivery date,
  rather than the check date. Delivering a task again makes it await a new check.
- **Memory:** candidate, confirmed, and rejected lessons; disputed-entry filtering,
  search, sources, scope, and automatic verification results. You can reject a lesson,
  request another automatic check of a candidate, or confirm it with required evidence.
  Decisions are written to the existing memory ledger and apply to subsequent agent
  operations. Reverification runs while idle on its normal schedule; the button does
  not start a second daemon.

Screens include office and daemon filters. Office membership follows **current seating**,
not a daemon's historical location. Daemon labels include the project and ID to distinguish
identical names.

Statistics lists start with **20 records**: the daemon table, task journal, suggestions,
outcomes, analytics, retrospectives, rework, and entries from each memory source. Each
nonempty list has a **Showing N of M** counter at the bottom and a **Show more** button
when records remain. The button adds the next 20 records to that section only. Automatic
refresh preserves the expanded count; changing filters, search, or sorting resets the
relevant list to its first 20 records. Totals, charts, and CSV use the full filtered
selection, regardless of how many rows are expanded.

Data refreshes every 30 seconds. While you edit prices, a lesson, or a rework request,
filters and refresh pause. Input is preserved when you switch sections and return within
the same browser tab. Reloading the page discards unsaved input; changing the interface
language first warns about drafts, including those retained in inactive sections.

On narrow screens, analytics, retrospectives, and rework appear as records with field
labels; wide statistics tables scroll within their own container. Empty memory stores
are grouped in a collapsed list. Viewing memory does not import or delete entries: the
daemon continues to manage their lifecycle.

The dashboard only accesses stores resolved from the current daemon configurations and
service settings; it does not accept arbitrary paths from the browser. `--no-control`
disables memory changes. Demo mode and viewing another `--logs` directory do not expose
working memory.

## Feature switches and live GigaCode output

Open a daemon in its office → **Settings** → **Daemon features**. Each feature offers
**Enable**, **Disable**, and **Use configuration**. The switches control Jira, Bitbucket,
memory, candidate collection, automatic lesson verification, independent review, backlog
exploration and learning, retrospectives, Jenkins, manually requested rework, and linked
task ordering. Starting and stopping the daemon remain separate panel actions.

A UI override takes priority over configuration files, service settings, and environment
variables. **Use configuration** removes the override and restores the usual precedence.
The setting applies to the entire selected daemon, including its services; applied values
are shown separately for each service. Connection addresses, tokens, test commands, and
schedules remain configuration settings. Enabling a feature does not create a missing
connection or bypass its schedule or limits.

Overrides are saved atomically in `logs/{instance}-features.json` and survive restarts
and code updates. A task or background operation finishes with the settings it started
with; new values apply at the next safe loop boundary. The panel distinguishes **waiting
to apply**, **applied**, and **will apply at startup**. A running daemon wakes without
waiting for the full polling interval. Use **Stop** to interrupt it immediately.

Disabling Jira stops task retrieval, backlog exploration, retrospectives, and manually
requested rework; queued rework is preserved. Bitbucket and memory verification can run
independently. Disabling memory stops reading, collecting, and automatically verifying
knowledge without deleting existing entries. Manual memory viewing remains available in
the dashboard. Disabling Jenkins skips deployment; disabling review skips the independent
review stage. The other task stages continue. `--no-control` makes switches read-only;
they also cannot be changed in demo mode or when viewing another log directory.

The UI works without adding new configuration keys. See the
[configuration reference](CONFIGURATION.en.md) for every setting in this mechanism.
The other switches correspond to the existing `bitbucket.enabled`, `memory.enabled`,
`memory.auto_append`, `memory.auto_verify`, `review.enabled`, `explore.enabled`,
`explore.learn`, and `retro.enabled` keys. A corrupted override file stops the polling
pass instead of reverting to potentially unwanted defaults.

**GigaCode monitoring:** open a daemon → **GigaCode logs**. The timeline updates through
SSE during execution. Technical entries expose tool names, arguments, results, and stderr.
The existing launch command, including its shell wrapper, stdin, and permissions, is
preserved; stdout uses `stream-json`. `thinking` blocks are not stored. Status labels
follow CLI events: a shell call is shown as command execution, without assuming that the
command runs tests.

Logs are available immediately, without sign-in, keys, or role separation. **Activity**
shows a concise timeline; **GigaCode logs** shows expandable technical events. By default,
the dashboard listens only on `127.0.0.1`.

Each daemon has a separate `logs/{instance}-cli-events.json`, containing the latest 256
events from the current or most recent run, with up to 6,000 characters of technical
detail per event. Every run receives its own `executionId`. After an SSE interruption,
the browser automatically receives the current saved window; this is not an unlimited
archive of all events. Limits are 1,048,576 characters per JSONL line and 2,097,152
characters for the final answer. A parse error or exceeded limit prevents the run from
being counted as successful. A slow browser does not block the CLI: snapshots are written
separately. Up to 16 technical/user event-stream subscriptions are allowed simultaneously.

The pipeline uses only the main agent's `result`, not results from tools or subagents.
Exit code 0 without a successful `result` is an error. Final stage logs and their rotation
are preserved; **Generation result** shows the main generation output. The adapter and
tests use the supplied Qwen Code / GigaCode v26.9.64 schema. Verification against the real
corporate CLI takes place in your network.

## City, offices, themes, and the Artel mark

**Team** shows a dimensional building in a city scene: front and side walls, a roof,
pavement, a road, occasional cars, and pedestrians who enter the building. Each building
has at most **16 offices**. Offices 1–16 occupy the first building, 17–32 the second,
and 33–48 the third. Buildings alternate between the two sides of the road. An address
such as **Building 2 · floor 3** is derived from the office's persisted ordinal, so
renaming, searching, or deleting a neighboring office does not move anyone. Gaps remain
as vacant floors.

More buildings bring more pedestrians, cars, houses, shops, and cafés. A school appears
with the first building, then one more for every four additional buildings. Schools have
a gabled entrance, a flag, and grounds; shops have display windows and awnings. These
are district scenery; Artel buildings contain the working offices.

Buildings are staggered with open spaces in front of their entrances. Houses and shops
occupy side lots, while schools and their grounds sit in the back row. Scenery does not
obscure selectable façades. **Building 1** and **Building 2** labels remain readable
across zoom levels. Select a label to focus that building; labels are also keyboard
accessible. Pedestrians approach visible entrances while walking around buildings.

**Building names** above the map opens a form: choose a building, enter a name of 1–60
characters, and select **Save**. The name updates on the map, in the switcher, in previews,
and in office addresses, and can be used to search for teams. Long map labels are
ellipsized; the full name remains available in a tooltip and the building list. **Cancel**
or Escape closes the form without saving. Names are stored on the server in
`building.json.buildings.json` beside the seating data and survive restarts and normal
updates. Renaming never moves offices or daemons. Generated building names follow the
interface language; custom names, including names that resemble defaults, are preserved.

The **Whole district / Building …** switcher focuses a selected building so its floors
remain accessible in a large city. Selecting an office below the scene also focuses its
building. Each office occupies a floor. Hover over a façade to open a preview on the
right with actual seating and current counters. The preview stays open as the pointer
moves into it; **Open office** opens the full animated daemon scene.

The map supports free zooming and panning. The mouse wheel zooms around the pointer;
dragging pans the scene. On a touchscreen, drag with one finger and pinch with two.
The page scrolls outside the map, including over the controls below it. **− / +** cover
50–800% of the automatic view; **Whole district** frames every building again. When the
map has focus, use **+ / −**, arrow keys, and **Home**. Selecting a building or office
fits the view to that building again. Status updates preserve your manual view; reloading
the page restores the overview. Zooming also works while animation is paused.

On a phone, tap a floor or its button below the building; the preview appears below the
scene. Floor buttons support keyboard navigation, arrow keys change the selection, and
Escape closes the preview. **Seating** and **Manage offices and seating** expose office
renaming, empty-office deletion, dragging daemons, and the **Move** form. Search highlights
matching floors while preserving building geometry and other floor numbers. Addresses
come from the server catalog and survive renaming and restarts.

**Pause scene** stops city and character movement; statuses and logs keep updating.
The system reduced-motion preference is respected. The city renders locally without
external libraries or CDN requests. Animation pauses when the tab is hidden or the scene
is not visible. City rendering is capped at 30 frames per second.

The header offers **System**, **Light**, and **Dark** themes. System follows the operating
system preference; an explicit selection is saved in the browser. The theme applies to
sections, forms, logs, the city, and the background around the office canvas. The office
artwork retains its original palette. Artel's mark is a teal “A” inside a gear and is also
used as the favicon. The favicon color follows the actual light or dark theme, including
system changes when **System** is selected.

## Server launch arguments

```bash
python3 office_dashboard/server.py                    # → http://127.0.0.1:8765/
python3 office_dashboard/server.py --cat              # with Kokoshka the cat
python3 office_dashboard/server.py --demo 6 --speed 3 # six simulated daemons, no Jira or GigaCode
```

| Flag | Purpose |
|---|---|
| `--logs PATH` | Daemon log folder; defaults to the project's `logs/` directory. |
| `--port 8765`, `--host 127.0.0.1` | Listening address. `--host 0.0.0.0` exposes it to colleagues on the internal network; logs and controls are available to everyone who can reach that address. |
| `--cat` | Add Kokoshka; disabled by default. |
| `--prices PATH` | Token price file; defaults to `office_dashboard/prices.json`. |
| `--no-control` | Disable daemon, retry, feature, prompt, and memory control; names, prices, and office appearance remain editable. |
| `-v`, `--verbose` | Detailed HTTP server logs. |
| `--names PATH` | Daemon name file; defaults to `office_dashboard/names.json`. |
| `--characters PATH` | Selected-character file; defaults to `office_dashboard/characters.json`. |
| `--assets PATH` | An alternative asset directory; defaults to bundled `office_dashboard/assets`. |
| `--demo N`, `--speed K` | Simulate N daemons with two weeks of history at K times normal speed. |

You can start or stop the dashboard at any time; daemons do not depend on it. New instances
are discovered automatically in `logs/`. Instances using an older script without
`state.json` are reconstructed from logs and marked **from logs**.

## Team section

- **One character represents one daemon.** Labels above it show its name and activity:
  `HRPPA-514 · coding 12:03`, `git push`, `deploy → ift + migration`, or `→ Review`.
- **Daemon card:** name and configuration item (CI), or the project key when no CI is
  configured; current activity; and the task's service, such as back/web. While idle,
  it shows **time since the last real task**, such as “idle for 1 h 10 min · after CRMX-780”.
  This starts at the last completed task, or at startup if no task has finished. Jira
  polling and backlog exploration do not reset idle time; the next poll is shown in
  a tooltip.
- **Buildings and offices:** the overview groups rooms by project and service and shows
  residents and problems. Each room holds up to 10 daemons. Seats persist on the server
  in `building.json`, even when a daemon disconnects. Only the open office is animated.
  Seven base characters and six palettes give 42 appearance combinations; a palette is
  assigned automatically and can be changed in the character panel. See the
  [architecture guide](../office_dashboard/README.en.md).
- **Stages in the office:** enter through the front door → sit and type at a desk
  (GigaCode) → walk to the printer (Git) → return to the desk for review and fixes →
  visit the meeting room (Jenkins) → go to the task board (Jira) → celebrate or react
  to an error. While idle, characters sometimes approach the board to explore the
  backlog. Office, meeting-room, and entrance doors open on approach and close behind them.
- **Select a character or card** to open the daemon panel. Tabs are **GigaCode logs**,
  **Activity**, **Settings**, **Retries**, **Placement**, **Daemon log**, and, when a task
  is available, **Generation result**. Logs support copying and optional auto-scroll.
  Close the panel with its button or Escape; focus returns to the card.
- **Pause animation** stops character movement while statuses and logs continue updating.
- **Double-click a character**, or select **Check Jira now** under Settings, to poll
  Jira immediately without waiting for the remaining interval. The character runs to
  the board with a “Checking Jira!” message.
- **Stop** under Settings works at any time, including during generation or review.
  The dashboard asks for confirmation and shows what the daemon is doing. The daemon
  interrupts GigaCode and exits within seconds; its character leaves the office. On the
  next launch, the interrupted task needs review and approval under **Retries**. Before
  starting a new generation, the daemon preserves its unfinished commits under
  `refs/ai-team-interrupted/…`. The supervisor does not automatically restart a daemon
  stopped this way.
- **Start** is available for a stopped daemon when daemons are managed by the supervisor
  (`python3 artel.py start`). The dashboard asks the supervisor to start it. Without a
  supervisor, start the daemon in a terminal.
- **Names:** select ✎ beside a name in the daemon panel or statistics. Names are stored
  in `office_dashboard/names.json` and override `general.name` in configuration.
- **Character and office:** use **Placement** in the daemon panel to choose an office
  and appearance. A character changes immediately without restarting. **Use configured
  character** restores configuration or automatic selection. Precedence is dashboard
  selection → `general.character` → automatic assignment. Automatic choices are stable,
  based on the daemon ID and preferably avoiding characters already assigned to others,
  and are saved in `office_dashboard/characters.json`. Restarting the dashboard does not
  change everyone's appearance. An unknown configured character produces a panel warning
  and falls back to automatic selection.
- **No heartbeat:** after 45 seconds without a heartbeat, the character becomes a gray ghost.
- **Version:** cards show the daemon code version; older versions are marked ⚠.
  Restart them with `python3 artel.py restart --outdated`.

## Office life

Walking has smooth acceleration and braking, with step speed matched to movement.
Activities include discussing scenarios at the board and chatting over coffee. Idle
daemons can visit other offices automatically; **Visit colleagues** sends an available
character to available colleagues. A guest uses the lounge while keeping its permanent
seat. Receiving real work immediately ends the visit.

**Reward** and **Reprimand** trigger different animations: a star-and-confetti celebration
or a thoughtful reaction with dialogue. These are scene interactions; they do not change
task requirements, quality statistics, or agent memory. Visits and reactions belong to
the current browser tab. After a reload, characters return to their permanent seats.
The operating system's reduced-motion setting disables extra jumps and reaction particles.

## Idle activities

While daemons wait for tasks, they can:

- Chat in pairs with questions, answers, laughter, friendly shoulder pats, and package handoffs.
- Sit on a sofa or armchair, drink coffee, talk, and laugh while seated.
- **Play PlayStation:** one character takes the console from the cabinet and connects it
  to the TV; two sit with gamepads, celebrate wins, and eventually return the console
  to the drawer.
- Visit the kitchen for coffee, the water cooler, a window, or a colleague writing code.
- Leave the office for a walk and return.
- Celebrate a colleague's completed task and wave to arriving coworkers.

There are about 30 spoken thoughts, such as “Lunch soon?”, “I need a vacation…”, and
“That bug again…”, plus 16 short dialogues such as “When is the release?” → “Yesterday”.
Any real work immediately interrupts a break.

## Statistics tab

**Cost.** **Set token prices** in the cost tile opens a form for prices per million input,
output, and cached tokens, plus the currency. Prices are stored in
`office_dashboard/prices.json`, or the file selected with `--prices`. Cost uses the usage
reported by GigaCode: uncached input at the input price, cache at its own price (cache is
part of input), and output at the output price. If the CLI reports only total tokens,
cost is estimated at the input price and marked “≈”. Costs appear for each task, for
each daemon, and for the selected period, and are included in CSV. Hover over a task's
cost to see its calculation.

View how many tasks each daemon completed, which tasks they were, and when: today,
the last 7 days, the last 30 days, or all time.

**Statistics count Jira tasks, not runs.** A task attempted three times with two failures
followed by success counts as one completed task. Its outcome follows the latest attempt;
time, tokens, and cost include all attempts because they reflect actual expenditure.
The task journal's **Attempts** column, such as “3 (2 ✗)”, expands to show each attempt
and its outcome or error. The daemon table shows retries. Tiles include success rate and
the share completed **on the first attempt**. **Not completed** distinguishes failures
from tasks waiting for clarification, and shows the number of failed attempts. A task
belongs to the period of its latest attempt, with all earlier attempts included. The
✓ / ⚠ / ✗ office-card counters also count tasks since daemon startup.

**Idle suggestions.** The suggestions tile shows how many backlog tasks were investigated
and how many runs finished without a comment. The daemon table and the suggestion journal
show when a run occurred, which daemon and task it involved, its outcome (posted, no
result, timeout, or posting failed), duration, tokens, and cost. Task links point directly
to the comment. Exploration expenses contribute to overall token and cost totals and
are shown separately in the tile caption. Data comes from `logs/{instance}-proposals.jsonl`,
written by daemons since version 2.5.0; earlier exploration is not recorded there.

Other metrics include average generation time, Jenkins deployments, tasks by day, daemon
rankings, and the task journal with Jira links. **Download CSV** exports one row per Jira
task for Excel, including **Attempts** and **Failed attempts**. CSV respects the selected
period, office, and daemon; text search applies only to the on-screen results. Export
headings and standard status labels follow the chosen interface language; original task
messages and names remain unchanged.

**Delivered-task outcomes** show whether a daemon is improving, based on retrospectives:

- **Merged unchanged:** the share merged as delivered among tasks with known outcomes.
- **Edited by humans:** merged after people changed the daemon's code, including line counts.
- **Without merging:** the branch was deleted without a merge. **Follow-ups after merge**
  counts corrective commits on the base branch.
- **Awaiting outcome:** not yet merged or not yet checked by a retrospective.

The chart groups outcomes by delivery week and plots the unchanged-merge share over time.
The table groups daemons and their services, such as back/web; the daemon filter applies
here too. Retrospectives check tasks after several days, so **Today** and **7 days** show
the latest 12 weeks in this section. Data updates after each retrospective, normally once
a week overnight or when invoked with `--retro`.

## Kokoshka

With `--cat`, Kokoshka lives in Artel: she wanders freely, sleeps on the sofa and rug,
sits beside daemons, and meows when clicked. Daemons call to her and approach to pet her.

For deployment and upgrades, see the [update guide](../UPDATE.en.md). For implementation
checks, see the [test guide](../tests/README.en.md).
