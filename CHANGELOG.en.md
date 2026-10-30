# Changelog

**English** · [Русский](CHANGELOG.md)

This is a concise history of features confirmed by previous documentation and the current
code, rather than a reconstructed list of every commit. Operational instructions are in the
[README](README.md) and [configuration reference](docs/CONFIGURATION.en.md).

## 2.30.0

- A Russian / English selector beside the appearance setting translates sections, forms,
  tooltips, statistics, control messages, character dialogue, and CSV exports.
- The browser remembers the language. Switching languages warns about unsaved changes;
  names, tasks, prompt contents, memory entries, and raw logs remain unchanged.
- English README, a separate office view, and full-size interface screenshots.
- Detailed configuration references in English and Russian: precedence, environment
  variables, services, TLS, models, memory, test commands, and configuration recipes.
- English versions of all project guides and instructions, with links between languages.
- Office scene assets included in the public repository with the rights holder's authorization.

## 2.29.0

- A dedicated prompt editor: per-daemon developer/tester profiles, installed execution
  subagent, instructions for seven stages, preview, and reset to configuration defaults.
- Behavior settings are stored per daemon, applied after current work finishes, and
  considered when approving retries from an older configuration.
- Statistics, analytics, retrospectives, rework, and memory lists show 20 records at a
  time with a “Show more” button. Totals and exports use the complete selection.
- Previous releases, presentations, and build materials moved to a separate archive with
  checksum verification. Source code, required assets, and local data were preserved.
- Added `.gitignore`, portable line endings, and repository preparation instructions:
  secrets, runtime data, builds, and original third-party assets were excluded from Git.

## 2.28.0

- Re-examine changed stories and update the daemon's existing comment.
- A separate `BLOCKED` outcome: ask a question in Jira and wait for clarification instead
  of automatically retrying.
- Jira notifications for decisions that need the owner's input.
- The favicon color follows the selected theme.
- Short README, runbook, a unified configuration reference, and separate guides.

## 2.27.0

- City map zoom with the wheel or a two-finger gesture, panning, zoom buttons,
  and keyboard navigation.

## 2.26.0

- Building names saved on the server, searchable and included in office addresses.

## 2.25.1

- Improved placement of buildings and surrounding scenery, label visibility, and entrances.

## 2.25.0

- A district with several buildings: up to 16 offices per building, buildings on both sides
  of the road, and more surrounding scenery, cars, and pedestrians as the district grows.

## 2.24.0

- A three-dimensional building on a city street, with an office preview when selecting a floor.

## 2.23.0

- Offices on the floors of a pixel-art building, light/dark themes, and the Artel emblem.

## 2.22.0

- Redesigned dashboard navigation, screens, and narrow-screen behavior.

## 2.21.1

- Removed the separate owner login: live GigaCode events and tool details are directly
  available in the daemon panel.

## 2.20.0

- Process all new comments on a selected pull request together, then reply to each
  comment separately. The Bitbucket certificate setting became optional.

## 2.19.1

- A complete update archive with a SHA-256 manifest and verification of installed files.

## 2.19.0

- Backend → frontend ordering for linked tasks, Development branch checks, and the
  `backend-ready` label.

## 2.18.0

- UI feature toggles for daemons, persisted choices, and application at a safe boundary.

## 2.17.0

- Manual rework after changed requirements, with a separate queue, branches, and analytics.

## 2.16.0

- Start the dashboard and daemons together with `artel.py up`; Windows launch commands;
  analytics, retrospective, and memory management screens.

## 2.15.0

- Handle feedback on the daemon's own pull requests in Bitbucket Server / Data Center
  through a Python REST client.

## 2.14.0

- An execution subagent definition with the OpenSpec lifecycle and explicit final result signals.

## 2.13.0

- Configurable base branches, including per-service overrides.

## 2.12.0

- A persistent retry journal, pauses, exclusions, and explicit approval after configuration changes.

## 2.11.0

- Managed updates: wait for current work, stop processes, and restore them afterward.

## 2.10.0

- Rename offices, delete empty offices, and move daemons by dragging them between offices.

## 2.9.0

- Manual daemon placement and statistics filters by office.

## 2.8.0

- Multiple offices, permanent seats, and character appearance variants.
