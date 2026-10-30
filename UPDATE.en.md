# Updating Artel on your mini PC

[English](UPDATE.en.md) · [Русский](UPDATE.md) · [Home](README.md)

Use `update_artel.py` from the **new** version. Python 3.9+ is required; no additional packages
are needed. The script runs locally on the mini PC with two separate directories: the extracted
new version and the existing installation. It does not download code or change OS startup
settings. In normal mode you manage processes manually; `--managed` waits for work to finish
and restores the previous processes automatically, as described below.

## Complete update package and transfer verification (2.19.1)

Use a single archive for transfer. It includes all daemon and server modules, dashboard sections,
nested sprites and their JSON metadata, subagent templates, and documentation. Build it on the
computer that has the complete new project version:

```bash
python3 build_artel_release.py --output output/artel-2.30.0-update.tar.gz
```

The archive excludes working configurations, memory, logs, secrets, office settings, and
presentations. It updates an existing installation; it does not provision a new one.
`artel-release.json` contains the file list and SHA-256 hashes. If a file is missing or damaged,
the new updater refuses to proceed before stopping any processes. Use the updater from the
extracted package: older scripts do not validate the manifest. The root `README.md`, `UPDATE.md`,
and package builder are also updated.

Copy the archive to `~/Downloads` on the mini PC. Then run the following commands **on the mini PC**.
`~/Documents/artel` is an example of the active installation path; replace it with yours.
Each extraction creates a separate temporary directory to avoid mixing versions:

```bash
ARTEL_RELEASE_DIR="$(mktemp -d "$HOME/artel-release.XXXXXX")"
tar -xzf "$HOME/Downloads/artel-2.30.0-update.tar.gz" -C "$ARTEL_RELEASE_DIR"

python3 "$ARTEL_RELEASE_DIR/artel-new/update_artel.py" \
  --source "$ARTEL_RELEASE_DIR/artel-new" \
  --target "$HOME/Documents/artel" --managed --dry-run

python3 "$ARTEL_RELEASE_DIR/artel-new/update_artel.py" \
  --source "$ARTEL_RELEASE_DIR/artel-new" \
  --target "$HOME/Documents/artel" --managed --wait-timeout 14400

python3 "$ARTEL_RELEASE_DIR/artel-new/update_artel.py" \
  --source "$ARTEL_RELEASE_DIR/artel-new" \
  --target "$HOME/Documents/artel" --verify-only

cd "$HOME/Documents/artel"
python3 artel.py status
```

Run the commands sequentially in the same terminal. If a command fails, stop and read its
message. The already-running processes must support the 2.11.0+ maintenance protocol to use
`--managed`. If your data lives outside the installation, add `--data-path` to the update command
as described below.

Before copying, the script reports absolute paths, counts of new, changed, and matching files,
and the module, interface, and asset contents. After copying, it verifies the contents of
**every** package file in the target installation. A verification failure rolls back affected
code. `--verify-only` checks for a match without stopping processes or writing files; a mismatch
returns a nonzero exit code. Extra files in the old installation are not deleted. The older
“updated — 3” message combined new and replaced files and did not prove that the package was complete.

A normal project directory without a manifest remains supported, with an explicit warning:
the updater cannot establish its completeness. Use the archive built above for transfers.

### If the old dashboard or sprites remain after updating

1. Run `--verify-only` from the new package with the same `--target`. It identifies missing or
   different files. Make sure `--target` is the directory from which the dashboard runs.
2. Open the running dashboard at its HTTP address, usually `http://127.0.0.1:8765/`, then perform
   a hard refresh. `output/Artel_Interactive.html` is a separate presentation, not the live
   dashboard; updating the code does not change it.
3. Check the original launch command: `--assets` and `OFFICE_ASSETS` may point to an old external
   pack. `--managed` preserves those settings. Updated bundled sprites are under
   `<installation>/office_dashboard/assets`. To use them, change the asset path in your launch
   settings and restart the dashboard. The updater does not overwrite an external pack;
   `--data-path` only includes it in the backup.

Installed definitions under `~/.gigacode/agents/` are updated separately; see
[Subagent definitions](#subagent-definitions).

## Manual update procedure

1. Copy the new version to a separate directory on the mini PC, for example
   `~/Downloads/artel-new`. Do not replace the working installation with that directory.
2. Preview the plan; this does not change files or stop processes:

   ```bash
   python3 "$HOME/Downloads/artel-new/update_artel.py" \
     --source "$HOME/Downloads/artel-new" \
     --target "$HOME/Documents/artel" --dry-run
   ```

3. Wait for current tasks to finish. Temporarily disable automatic restarts through launchd
   or another process manager if configured. Stop the daemons and, separately, the dashboard
   using your normal method. For Artel's supervisor:

   ```bash
   cd "$HOME/Documents/artel"
   python3 artel.py stop
   ```

4. Run the update, replacing the example paths with yours:

   ```bash
   python3 "$HOME/Downloads/artel-new/update_artel.py" \
     --source "$HOME/Downloads/artel-new" \
     --target "$HOME/Documents/artel"
   ```

5. Only after a successful update:

   ```bash
   cd "$HOME/Documents/artel"
   python3 artel.py check
   python3 artel.py start
   python3 artel.py status
   ```

   If you use launchd, restore the previous startup mechanism instead of separately running
   `artel.py start`. Start the dashboard with its original command and parameters. Refresh
   the browser and check daemon names, offices, seats, and statistics.

## What is preserved

Before replacing the first file, the updater creates a full copy of the working installation
in the neighboring directory `artel-backups/artel-DATE-TIME-…/installation`. The backup contains
`manifest.json`, listing the affected files and update outcome. Each backup directory is
accessible only to its owner. You need enough free space for the entire installation, including
any repositories stored inside it. If backup creation fails, code is not changed.

The updater replaces root scripts, `jira_gigacode` and dashboard server Python modules, static
interface files, supported asset types, documentation, and the two templates
`config/example.json.sample` and `config/example-services.json.sample`. Extra files are not
removed. **Working `config/*.json` files, `memory/`, `logs/`, `.env`, names, characters, pricing,
`building.json`, `building.json.rooms.json`, and `building.json.buildings.json` are not copied
from the new version and are not overwritten.** Configuration filenames and daemon identifiers
remain unchanged.

If memory or settings live outside the working installation, through `memory.path`, environment
variables, or dashboard arguments, explicitly include every external file/directory in the backup:

```bash
python3 "$HOME/Downloads/artel-new/update_artel.py" \
  --source "$HOME/Downloads/artel-new" \
  --target "$HOME/Documents/artel" \
  --data-path "$HOME/artel-data/memory" \
  --data-path "$HOME/artel-data/dashboard"
```

External data is not updated. It is backed up under `external/0`, `external/1`, and so on, with
original-path mappings recorded in the manifest. The script does not try to infer external
paths from configuration or environment variables. Symlinks in a full backup remain symlinks;
to copy the contents of an external directory, explicitly provide it through `--data-path`.
Symlinks in paths of code being updated are rejected.

`--backup-dir /path` changes the backup location, which must be outside both the source and the
installation. Concurrent updates of the same installation are locked out. Running-process
checks provide additional protection; disable automatic restarts beforehand for a manual update.

## Errors and recovery

If file replacement fails, the updater automatically restores affected code files from the
backup and removes new files it created. It does not restore memory or runtime state over
current data during this rollback. Rollback failures are reported explicitly, and the original
backup remains available.

Automatic rollback is not guaranteed after a power loss or forced termination. Do not start
a partially updated installation. For full recovery, stop processes and automatic restarts,
rename the failed installation directory, then copy `installation` from the backup to the
original installation path. Restore external data separately using the manifest, only if needed.
The script does not delete backups.

## Automatic waiting and process restoration (2.11.0)

Once the **already-running** daemons, supervisor, and dashboard support version 2.11.0, use:

```bash
python3 "$HOME/Downloads/artel-new/update_artel.py" \
  --source "$HOME/Downloads/artel-new" \
  --target "$HOME/Documents/artel" \
  --managed --wait-timeout 14400
```

You can still add `--dry-run` first. `--data-path` and `--backup-dir` also work in managed mode.

The update sequence is:

1. Daemons stop taking new tasks. The current task finishes its entire pipeline, including
   reporting and outcome recording. Already-started exploration, retrospectives, or memory
   verification finish too. Jira polling must also complete.
2. Each process acknowledges a safe point. The dashboard stops accepting requests and drains
   current HTTP handlers and SSE connections. The supervisor stops launching new daemons.
3. After all processes acknowledge, child daemons exit. The supervisor, dashboard, and daemons
   started without the supervisor remain in a minimal waiting state, without doing work.
   This preserves their original environment and launchd relationship without exporting
   secrets into files.
4. The updater creates a backup and replaces code. Waiting processes then replace themselves
   with the new version through `exec`, preserving the interpreter, arguments, environment,
   and working directory. The supervisor restores active configurations without enabling
   ones that were previously stopped.
5. The script waits for restarted processes to register and child daemons to return. This
   confirms startup, but does not replace checking Jira/Jenkins and real tasks through
   `artel.py status` and logs.

If **waiting for tasks** times out, code remains unchanged: maintenance is cancelled and the
current task is not interrupted. An installation error followed by successful rollback restores
the old code. If stopping or rollback cannot be confirmed, automatic resumption is blocked to
avoid starting a partially updated installation.

The first upgrade from 2.10.0 or earlier must use the manual procedure above. Old processes
cannot safely acknowledge completed work, and `--managed` refuses to force-stop them. Normal
`--managed` operation does not require launchd changes: controlling processes keep their PIDs
and do not exit before `exec`. Do not run another updater or perform a manual restart concurrently.

Maintenance state lives in `.artel-maintenance/` and is excluded from backups. If the updater
crashes after beginning code replacement, processes remain waiting. Check the latest backup's
`manifest.json`, finish restoring code if necessary, and delete `.artel-maintenance/request.json`
**only after verifying installation integrity**. Removing that file allows waiting processes
to resume. If uncertain, stop all processes and perform full recovery as described above.

### Subagent definitions

Since version 2.14.0, updates also transfer templates under `subagents/`. The installed file in
`~/.gigacode/agents/` or the working repository's `.gigacode/agents/` is not changed automatically.
See the [subagent instructions](subagents/README.en.md) for installation and preserving the
previous definition.

## After upgrading to 2.29.0

Restart the daemons and dashboard, then refresh the page. The **Prompts** tab lets you set each
daemon's role, executor, and instructions for seven stages. Settings saved through the UI apply
between tasks without another restart. They are stored in `logs/{instance}-prompts.json` and
preserved by the updater. The selected subagent must be installed in GigaCode; the **Tester**
profile also works with the standard executor. See [Prompts](docs/PROMPTS.en.md).

Statistics tables and working lists show 20 records initially; **Show more** adds the next batch.
Totals, charts, and CSV exports still include every record in the selected period.

## After upgrading to 2.28.0

Restart the daemons and dashboard, then refresh the page. Update the installed subagent definition
using the [instructions](subagents/README.en.md): a block containing a concrete question was added
before `CODE_GENERATION_BLOCKED`. Old reports without that block remain supported.

- `BLOCKED` waits for clarification in Jira without increasing the error counter. Returning
  to the backlog uses a safe direct transition into one of `explore.statuses`.
- Description or discussion changes allow the daemon to return to the task. Status changes
  and its own automatic reports do not trigger retries. Pauses, exclusions, and current
  search scope remain in effect.
- Previously explored tasks are reassessed after content changes with the existing minimum
  14-day interval, replacing the earlier comment. For old records without a fingerprint,
  the first read establishes a baseline; subsequent changes are tracked.
- Retry confirmation requests and disputed PR results are published in Jira when
  `jira.enabled` and `jira.result_comments` are enabled. Sends are kept in a persistent queue.
- The favicon follows the selected theme. The README is now a quick start; detailed guidance
  lives in the [Runbook](docs/RUNBOOK.en.md), [configuration reference](docs/CONFIGURATION.en.md),
  and [CHANGELOG](CHANGELOG.en.md).

The updater preserves `logs/*-blocked.json` and `logs/*-notifications.json` alongside existing
logs, memory, settings, and seating. The complete package includes `docs/`.

## After upgrading to 2.27.0

Zoom the district with the mouse wheel and pan by dragging. Touchscreens support one-finger
panning and two-finger zoom. **− / +** and **Fit district** buttons appear below the scene;
keyboard controls are **+ / −**, arrow keys, and **Home**. Refresh the dashboard page. Memory,
settings, building names, and seating remain unchanged. The package includes the new
`office_dashboard/static/js/office/city-controls.js` module; transfer the entire package using
the standard updater.

## After upgrading to 2.26.0

A **Building names** button appears above the map. Select a building, enter a name up to
60 characters, and save it. The name is shown on the map and in office addresses. The new
`building.json.buildings.json` file is created after the first rename and preserved alongside
seating during updates. For a manual dashboard transfer, keep all three files:
`building.json`, `building.json.rooms.json`, and `building.json.buildings.json`.
Restart the dashboard and refresh the page; renaming requires the new server API.

## After upgrading to 2.25.1

Building labels are fixed: the full name appears over the scene, remains legible on smaller
screens, and focuses the building when clicked. Buildings have more space between them;
houses and shops no longer obstruct office facades, and schools have moved to the back row.
Pedestrians walk around buildings and enter through visible doors. Refresh the dashboard page.
Settings, office addresses, and seating remain unchanged.

## After upgrading to 2.25.0

One building holds up to 16 offices. Additional buildings appear automatically on both sides
of the road; traffic, residential areas, shops, and schools grow with them. A switch above the
scene selects the entire district or an individual building. Addresses appear as “Building 2 ·
floor 3” and derive from the existing `building_level`: no new data migration is needed, and
names and seating are preserved. Removing an office does not shift neighboring addresses;
the empty floor remains in the building. Refresh the dashboard page.

## After upgrading to 2.24.0

**Team** now has a three-dimensional city scene with moving cars and pedestrians. Hover over a
floor to preview the office on the right; on a phone, tap the floor or the button below the
building. The preview offers entry into the office and access to seating. Renaming, deleting
empty offices, and moving daemons are grouped below the scene under office and seating management.
Floors that do not match a search are dimmed.

The office canvas background now respects the dark theme without light stripes. The logo and
favicon are turquoise. Perform a hard refresh: **Cmd+Shift+R** on macOS, **Ctrl+Shift+R** on
Windows/Linux. If an individual office is open, select **← Whole building**. No new daemon
settings are required; memory, offices, and permanent seats are preserved.

## After upgrading to 2.23.0

In **Team**, offices appear as floors of a pixel building. Select a floor name to enter it,
or a character to open its panel. Drag-and-drop and **Move** work between floors. On the first
catalog read, offices receive a permanent `building_level` in `building.json.rooms.json`;
existing offices, permanent seats, and names are preserved. A new office receives the next
available number at the top. Deleting an empty floor does not renumber other floors.

The header offers light, dark, and system themes. The choice is saved in the browser,
independently of daemon configurations. Restart the dashboard and perform a hard refresh.

## After upgrading to 2.22.0

Restart the dashboard and daemons (`--managed` does this for you), then perform a hard refresh:
**Ctrl+Shift+R** on Windows/Linux or **Cmd+Shift+R** on macOS. The new navigation includes
**Team**, **Statistics**, **Rework**, **Analytics**, **Retrospectives**, and **Memory**.
GigaCode logs and controls are available in separate tabs of the selected daemon's panel.

Runtime data formats are unchanged: memory, configurations, history, names, offices, seating,
characters, and pricing stay at their existing paths. You do not need to reconfigure daemons
or reconfirm lessons. Save or discard unfinished browser forms before refreshing.

## After upgrading to 2.21.1

Operator sign-in is no longer required. Open a daemon's **GigaCode logs** tab: technical events
are available immediately, while **Activity** shows a concise timeline. Restart the dashboard
and daemons; in `--managed` mode the updater does this. The legacy
`logs/.dashboard-owner-token` file from 2.21.0 is no longer used. Older executions are not
retrospectively converted into events.
