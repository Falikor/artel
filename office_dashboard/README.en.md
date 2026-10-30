# Artel daemons: dashboard architecture

[Русский](README.md) · **English**

For launch instructions and features, see the [dashboard guide](../docs/DASHBOARD.en.md).
For a quick start, see the [project README](../README.md). This document explains the
implementation for contributors extending the dashboard.

## Architecture

```text
daemon ──► logs/{id}-state.json     (atomic write, 10-second heartbeat) ┐
       ──► logs/{id}-history.jsonl  (one record per task attempt)       │
       ──► logs/{id}-delivered.jsonl, -outcomes.json                    ├─► server.py ──SSE──► static/js/ (scene, panel)
       ──► logs/{id}-agent.log                                        ┘          ├─ /api/history ─► js/stats/stats.js
                                                                                 └─ /api/quality ─► js/stats/quality.js
dashboard ──► logs/{id}-poke (double-click) ──► daemon polls Jira immediately
          ──► logs/{id}-stop (Stop)        ──► daemon interrupts GigaCode and exits
          ──► logs/artel-restart-{config} (Start) ──► supervisor starts the daemon
```

`server.py` is the entry point; use `python3 server.py --help` for flags. The server lives
in the `artel_dashboard/` package and uses only the Python standard library.

| Module | Responsibilities |
|---|---|
| `common.py` | Default paths, `tail_lines`, `pid_alive`, and atomic JSON writes. |
| `assets.py` | Asset discovery: characters (06), doors (07), lounge (08), furniture, and Kokoshka. |
| `daemons.py` | `read_all`: state files, legacy log parsing, latest task, names, and characters. |
| `stores.py` | `Names`, `Characters`, and `Prices`: settings editable in the interface. |
| `building.py` | Persistent offices, seating, appearance variants, building names, and default-name provenance. |
| `history.py` | Runs → Jira tasks; `group_tasks` takes the latest outcome and sums expenditure. Also idle suggestions, cost, and localized CSV. |
| `quality.py` | Delivered-task outcomes from retrospectives: shares, weeks, daemons, and services. |
| `insights.py` | Task-level aggregates, duration percentiles, retries, and measurement coverage. |
| `knowledge.py` | Memory stores resolved from configured daemons and services, listing, and decisions. |
| `features.py` | Per-daemon feature descriptions and persistent UI overrides. |
| `prompts.py` | Prompt configuration catalog, validation-backed editing, previews, and revision handling. |
| `handler.py` | HTTP API, SSE, and controls. `make_server` keeps stores on each server instance rather than in globals. |
| `app.py` | Arguments, demo setup, and startup. |

`static/js/` has no build step or third-party UI library. It uses ordinary `<script>`
tags sharing a global scope. **Script order in `index.html` matters:** definitions must
load before their consumers.

| File | Responsibilities |
|---|---|
| `core/i18n.js` | RU/EN selection, `tr`, `uiLocale`, explicit HTML annotations, persistence, and draft-aware language changes. Loads before other UI scripts. |
| `core/server-messages.js` | Exact translations and anchored patterns for known server-generated UI messages. |
| `core/theme.js` | System/light/dark preference and theme-specific favicon, applied before styles paint. |
| `office/scene-map.js` | Daemon stages (`STAGE`), map and path graph, seats, and dialogue. |
| `core/util.js` | `$`, `esc`, server time, image loading, and pathfinding. |
| `office/sprites.js`, `office/worker.js` | Sprites and daemon characters: walking and work stages. |
| `office/idle-life.js`, `office/lounge.js`, `office/cat.js` | Idle activities, the PlayStation cabinet, and Kokoshka. |
| `office/social.js` | Office visits, rewards, reprimands, and reduced-motion behavior. |
| `office/render.js` | Frame drawing: doors, objects, animation loop, and labels. |
| `office/building.js` | Office directory, seating, roster filters, moving residents, and inline office editing. |
| `office/city-model.js`, `office/city-controls.js`, `office/city.js` | District layout, camera and gestures, building/floor previews, labels, and building names. |
| `core/data.js` | Asset loading, SSE, and snapshot application. |
| `panel/cards.js`, `panel/drawer.js` | Daemon cards, the log/control panel, and scene clicks. |
| `panel/characters.js`, `panel/controls.js` | Character choices, Stop/Start, and names. |
| `panel/features.js`, `panel/monitor.js` | Feature switches and the live GigaCode execution timeline. |
| `panel/prompts.js` | Per-daemon and per-stage prompt drafts, previews, save/reset, and conflicts. |
| `core/pagination.js` | Independent sections with 20 records initially and 20 more per click. |
| `stats/quality.js`, `stats/proposals.js`, `stats/stats.js` | Outcome statistics, idle suggestions, and Statistics; charts use SVG without a chart library. |
| `stats/workspace.js`, `stats/requirements.js` | Analytics, retrospectives, memory, and rework screens. |
| `main.js` | Startup; the final script. |

During `reviewing` and `rework`, a character stays at its desk; during `exploring`, it
visits the board. Cards show `daemon_version` and mark outdated daemons with ⚠.

`demo.py` simulates daemons through the same `daemon_state.py` used by real instances.
It creates two weeks of history and 12 weeks of delivered-task outcomes, including
review, rework, backlog exploration, and one outdated daemon.

### Localization boundaries

The language selector is beside the theme selector. `artel-language` in localStorage
stores `ru` or `en`; existing installations default to Russian. `tr(ru, en)` selects
interface text, and `uiLocale()` supplies `ru-RU` or `en-US` for dates and numbers.
Static labels and accessibility attributes use explicit `data-i18n-*` annotations.
There is no general DOM-text replacement or translation observer.

Changing language reloads the page so labels initialized at script load are recalculated.
The guard checks actual form edits, prompt drafts for every daemon, and forms retained
in inactive workspace tabs. Successful saves and explicit cancellations use
`markFormClean`. Searches, filters, and theme preferences do not create unsaved-data warnings.

Known server UI messages pass through `translateServerMessage`; unknown strings are
returned unchanged. Never apply automatic translation to task text, memory entries,
logs, names, or model instructions. `building_title_custom` identifies generated versus
custom building names; absent provenance from older servers preserves the original name.
CSV accepts `lang=en` or `lang=en-US`; without it, the Russian export format is unchanged.
Language preferences never change daemon configuration or GigaCode behavior.

### API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/assets` | Background, characters (06), lounge set (08), doors (07), cabinet, kitchen objects, and cat with `--cat`. |
| GET | `/api/state`, `/api/stream` | All daemon states; SSE checks for changes once per second. |
| GET | `/api/history?days=N` | Tasks in the period (`records`, with attempts in `runs`) and idle suggestions (`proposals`). |
| GET | `/api/history.csv?days=N&lang=en` | One CSV row per Jira task; `lang` is optional. `office` and `id` filter office membership and daemon. |
| GET | `/api/quality?days=N&id=` | Delivered-task outcomes: totals, weeks, daemons, and services. |
| GET | `/api/insights`, `/api/retrospective` | Task analytics and individual retrospective outcomes; filters include `days`, `office`, and `id`. |
| GET/POST | `/api/memory` | Configured memory stores and lesson decisions; arbitrary paths are not accepted. |
| GET/POST | `/api/requirements` | Rework requests; POST submits or cancels a request. |
| GET/POST | `/api/features` | Applied/effective feature settings and UI overrides. |
| GET/POST | `/api/prompts` | Daemon catalog, prompt descriptors, and save/reset/preview actions. |
| GET/POST | `/api/prices` | Token prices. |
| POST | `/api/characters` | Character selection using `id` and `character`; an empty character resets selection. `variant` changes the palette. |
| GET | `/api/log?id=`, `/api/gigacode?issue=` | Tail of a daemon log or final GigaCode log. |
| GET | `/api/cli-live?id=`, `/api/cli-events?id=` | Live output snapshot and execution-event SSE stream. |
| GET/POST | `/api/names` | Daemon names, for example `{"id": "demo", "name": "Alex"}`. |
| POST | `/api/offices`, `/api/buildings` | Move residents, rename/delete offices, or rename a building. |
| GET/POST | `/api/retries` | Retry ledger and exclude/pause/resume decisions. |
| POST | `/api/poke` | Poll Jira now; returns `{"ok": true}` or a reason such as `busy`, `old`, or `offline`. |
| POST | `/api/stop` | Stop a daemon using `{id}-stop` for daemon 2.0.2+ or SIGTERM for an older local daemon. |
| POST | `/api/start` | Ask the supervisor to start a stopped daemon through `artel-restart-{config}`; returns `no_supervisor` when none is available. |

## Scene

Coordinates use the 1254×1254 background image; a character's position is the point at
its feet. `?debug=1` draws the path graph and points. Core scene settings live in
`static/js/office/scene-map.js`:

- `N`, `EDGES`: the path graph, using Dijkstra's algorithm. `SEATS` defines workstations;
  `LOUNGE` defines the sofa, armchair, and standing positions.
- `MEET`, `BOARD`, `PRINTER`, `CHAT_SPOTS`, `COOLER`, `KITCHEN`, `WINDOWS`: work-stage and
  break locations.
- `SOLO`, `DIALOGS`, `VISIT_DIALOGS`, `LINES`: dialogue. `ACTIVITY_WEIGHTS` controls activity
  frequency in the idle-activity implementation.
- `CAT_*`: Kokoshka's per-atlas-row scaling, walking locations, resting spots, and phrases
  in the cat implementation.

### Character animations

- **06_CHARACTER_ANIMATIONS** uses 128×128 frames, feet at 64,112, and ×1.125 scaling:
  walking in four directions, work, and chairs. Sideways walking is assembled from four
  phases—step → feet together → step → feet together—because the source atlas has the
  same leg separation in each frame. For `worker_orange_yellow`, `lounge_left` is replaced
  with a mirrored `lounge_right` through `ANIM_FIXES`.
- **08_LOUNGE_AND_SOCIAL** uses 160×160 frames with feet at 80,136. Sofa and armchair
  animations use `{sofa|armchair}_{sit|idle|drink|talk|laugh|game|game_win|stand}_{left|right}`.
  Sitting and standing smoothly shift the root between the approach point and the seat.
  It also contains `pat_shoulder/pat_received`, `give_item/receive_item`, and console clips.
  Rendering respects `flipX` and `frameOverrides`.
- `seatedClip` selects clips by furniture type; each animation has its own atlas and foot anchor.

### Doors: 07_DOOR_ANIMATIONS

`character_free_all_doors_open.png` is the background with open doorways. Animated panels
for the manager's office, meeting room, and entrance are drawn over it: eight frames over
800 ms, with fixed doorframes drawn above passing characters. A door opens when a
character's or Kokoshka's path crosses its line. Crossing is blocked until the door is
fully open; it closes after 1.1 seconds.

### Cabinet and PlayStation: 08

There is one console, moving through
`drawer` → `carried` → `installed` → `carried` → `drawer`. Cabinet states come from
`props/media_cabinet/manifest.json`. Ownership changes at the frame events
`console_pickup`, `console_install`, `console_pickup_installed`, and `console_store`.
A game starts only after both players are seated and the console is at the TV. If a
player is interrupted, the session ends; the next free daemon stores the console during
the `tidy` activity.

## Assets: `assets/`, approximately 41 MB

Office artwork, character sprites, lounge animations, doors, and Kokoshka are included
in the project. The default server path is `office_dashboard/assets`; `--assets` or
`OFFICE_ASSETS` can select another complete asset directory.

```text
02_ANIMATION/character_free_restoration_plate.png       original fallback background
03_INDIVIDUAL_TRANSPARENT_ASSETS/01_SCENE_SCALE_PNG/     cabinet, coffee machine, snacks: kitchen
04_CHARACTER_MODELS/03_CHARACTER_SPRITESHEETS/office/    TV, printer, plants
06_CHARACTER_ANIMATIONS/characters/<id>/                 seven characters, v3 set
07_DOOR_ANIMATIONS/                                      open-doorway background, three doors, manifest.json
08_LOUNGE_AND_SOCIAL/characters/<id>/                    lounge furniture, gestures, console
08_LOUNGE_AND_SOCIAL/props/media_cabinet/
08_LOUNGE_AND_SOCIAL/manifest.json
cat/                                                     Kokoshka
```

The artwork originated with the LennoxStudio Animated Corporate Office Asset Pack v1.1
and AI Artel additions (`ai-artel-main-2`, `ai-artel-main-3`). The project owner has included
the assets in this repository. Missing artwork does not prevent status, log, and control
screens from working; the interface reports unavailable scene assets.

## Buildings and permanent seats

The overview shows every office, occupancy, errors, and missing heartbeats. Selecting an
office opens its animated scene; selecting a resident opens its office and log. Only that
office's residents are rendered in the scene, while warnings from other offices remain
in the upper bar. Overall statistics remain available.

Grouping uses stable fields: `project` and `general.office_group` when provided,
otherwise `general.service`. Without either service/group setting, grouping uses only
the project. For example: `"general": {"office_group": "Payments"}`. A daemon that works
across several services can therefore keep a permanent department; transient
`detail.service` values do not move it. These fields appear in state after restarting a
daemon with version 2.8.0 or later.

Every 10 assigned seats form a separate office. Assignments persist in `building.json`
beside the `--characters` file and are shared by all browsers. An absent daemon keeps its
seat; newcomers take the next free seats. An office may therefore look partially empty
while its vacant cells are reserved. Changing the project or explicit group moves a
daemon to the new group. In the legacy log-only fallback, the project is inferred from
the log filename until a state file supplies the actual project.

Seven base models and six clothing palettes provide 42 combinations. Automatic base-model
assignment balances the selection without changing earlier choices. A palette is assigned
once and can be changed in the character panel. Assigning one base model manually to many
daemons may repeat combinations after the sixth resident; the system does not forcibly
change someone else's appearance. Palette replacement applies to walking, working, and
lounge frames. These are variants of existing models, not newly drawn characters. The
cache is limited to 256 frames; original atlases are not duplicated.

Building and statistics views do not animate a hidden office. Switching offices clears
characters, social-action queues, console state, and temporary seat reservations. The
shared board, printer, and meeting room use unique positions; other residents work from
their own seats instead of overlapping at a single point.

### Manual placement and office statistics

Open a daemon's **Placement** tab, select an office, and choose **Save placement**. You
can create a named office or restore automatic placement by project/service. Manual
selection persists in `building.json` and takes priority over configuration. Moving
releases the previous seat; absent daemons' seats remain reserved. A full target office
rejects the move with an explanation.

**Office statistics** opens a report for the selected room. Statistics includes office,
daemon, and period filters. Metrics, charts, suggestions, retrospective outcomes, and
task CSV honor the office filter; CSV also honors the selected daemon. After a move, the
daemon's history counts toward its new office: this reports the current team, not a
historical seating archive. **All offices** restores the overall view.

The interface uses a system font with Cyrillic support, without loading Google Fonts.
Secondary text has increased contrast; pixel artwork retains its original appearance.

### Office management

The building overview offers **Rename** and **Delete** for an empty office. A name change
does not change its ID or residents' seats. A room remains available for reuse or deletion
after its last daemon moves out. Seats reserved for absent daemons count as occupied.

Drag a daemon card onto another office; the target highlights. The server checks capacity
and persists the new seat. On failure, the daemon stays in the original office and an
explanation appears above the directory. The daemon-panel selector remains available
for keyboard and touch use.

The room catalog is stored beside seating in `building.json.rooms.json`. Existing rooms
are added automatically during an upgrade. When moving the dashboard manually, preserve
`building.json`, `building.json.rooms.json`, and, if buildings were renamed,
`building.json.buildings.json`.

### Map navigation

The mouse wheel zooms toward the pointer; dragging pans the map. On touchscreens, use one
finger to move and two to zoom. Normal page scrolling remains available outside the scene.
Below the map are **− / +**, the current zoom (50–800% of the automatic view), **Whole
district**, and animation pause. With the map focused, **+ / −** zoom, arrow keys pan,
and **Home** restores the overview. Building labels stay readable, and floor hit-testing
accounts for zoom. Selecting a building or office fits the view again; daemon state
updates do not reset it. Camera state lasts only for the open page and changes neither
seating nor server settings.

### Building names

Select **Building names** above the map, choose a building, and enter up to 60 characters.
**Save** updates map labels, navigation, and office addresses. **Cancel** or Escape closes
the form without writing. Names are shared across dashboard tabs and stored in
`building.json.buildings.json`, independently of browser storage. Updates preserve this
file; copy it with the other seating files when moving the installation manually.
Building numbers, floors, and daemon seats do not change when names change.

## Analytics, retrospectives, memory, and prompt screens

Analytics, Retrospectives, and Memory were added in version 2.16. Their endpoints are
`GET /api/insights`, `GET /api/retrospective`, and `GET/POST /api/memory`. Filters use
`office`, `id`, and, for time-based statistics, `days` (`0` means all time).
`insights.py` implements aggregates and `knowledge.py` resolves memory stores from
configuration. The UI is in `static/js/stats/workspace.js`; rework forms live in
`static/js/stats/requirements.js`.

The Prompts screen adds per-daemon roles, an execution subagent, shared instructions,
and seven stage-specific instruction fields. `jira_gigacode/prompt_control.py` owns
validation and persisted overrides; `artel_dashboard/prompts.py` serves the API;
`panel/prompts.js` manages browser drafts. Instructions are passed to the existing CLI
through stdin. Editing them does not bypass Artel's task selection, delivery checks, or
completion protocol. See the [prompt guide](../docs/PROMPTS.en.md) and
[subagent setup](../subagents/README.en.md).

Start the supervisor and dashboard together with `python3 artel.py up`. See the
[update guide](../UPDATE.en.md) for preserving runtime data and the
[test guide](../tests/README.en.md) for regression checks.
