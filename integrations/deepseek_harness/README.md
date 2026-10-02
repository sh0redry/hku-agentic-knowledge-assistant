# HKU AGENTS for DeepSeek Harness

## 0.19.2: empty booking record and F3 status corrections

Chrome Bridge 0.17.25 / booking parser 0.1.4 recognizes the confirmed default
empty record grid only on a complete authenticated unfiltered record page with
the exact six-column header and blank rows. Loading, filter controls, pagination
and unknown row shapes remain unverified. Record inspection waits for loading
to finish; an empty grid is never booking-success evidence.
F3 task cards now label read-only mode, distinguish preparation from checking
time, show the explicitly suggested candidate, and separate rule run counters
from F4 submission counters. No stored rules/authorizations are changed.

## 0.19.1: consolidated acceptance workbench

Agent Chat is the primary business entry; optional manual controls are collapsed.
Admin tests are grouped by SIS, Moodle, Portal and Library. The read-only task
center shows bounded F3/F4 snapshots with Hong Kong times and explicit unknown
submission warnings; it never retries, arms or changes a task. Auto-refresh is
opt-in and stops on unmount. Connection reads have visible deadlines, stale Host
responses are discarded, and Bridge disconnects trigger paced status refresh.

Admin's local checks and redacted report use fixed Host-only routes. They read
Core/Bridge versions, local catalog and gate status, never navigate or log in,
and never change a gate. Report generation includes only the last 100 local
Admin history summaries and human verdicts, not booking targets or private rows.
Check completion is not live acceptance. Chrome Bridge remains 0.17.24; a stale
or unreported extension version requires review, not an automatic upgrade.
See `docs/DESKTOP_PRODUCTIZATION_BATCH.md` for one combined acceptance session.

## 0.19.0: consolidated Desktop Library workflows

Business and Admin now have separate F1/F2/F3/F4 controls; the 23 Chat tools
remain read-only. Fixed authenticated operator RPC is not a generic write proxy.
F2 requires an explicit Admin gate and fresh exact confirmation. F4 requires
separate runtime enablement and exact arming, one verifiably empty target day and
one discussion-room session. Dry run cannot select/submit. Unknown outcomes are
terminal and never auto-retried. Restart Core and reload Chrome Bridge 0.17.24.
See `docs/DESKTOP_LIBRARY_BATCH.md` for the consolidated acceptance and limits.
The following sections describe earlier milestones, not current feature parity.

## Desktop 0.18.12: Start and connect HKU

### 0.18.14 rc.2 Chat toolview correction

The installed Desktop rc.2 client dispatches `tool.call.toolview` by tool name;
Host `presentCall`/`presentResult` hooks alone did not change its visible cards.
The browser bundle now registers all 23 HKU keys and declares the ui-tool client
dependency. Cards render preparing/running/completed/failed/interrupted states
and allowlisted `block.meta` summary fields only. They do not copy raw arguments,
private rows, or the canonical result JSON into the summary. A **View original
details** button uses Harness's existing inspector; model-facing output remains
unchanged. Missing metadata is explicitly unverified, never assumed success.
Client keyed-slot registration and actual rc.2 owner-prop shapes now have tests;
real Desktop display acceptance is still required after installation.

The business panel starts the registered Windows Core in the background, without
a token terminal, then checks the paired Chrome Bridge and HKU login. The Host
reads `%USERPROFILE%/.hku-agents/core-launch-v1.json`, registered by Core startup
or local installation. It runs only that installation's `.venv/Scripts/pythonw.exe`
and `project/app.py`, with no renderer-supplied commands, paths or arguments.
0.18.13 uses the GUI-subsystem `pythonw.exe` (instead of `python.exe`) without
detached console creation. Chrome Bridge waiting is 40 seconds to cover its
30-second reconnect backoff. Chrome extension 0.17.22 adds alarm-based retry
wakeup when MV3 suspends its service worker; reload that extension once.
This phase supports `http://127.0.0.1:7860` only. It checks public service health
before authenticated status, refuses unrelated port occupation and coalesces
clicks with a shared startup lock. Automatic launch forces supervised Library
writes off; no booking authority is added or persisted permissions changed.

Core survives closing Desktop so scheduled tasks are not interrupted. No stop/kill
endpoint exists. Chrome must be open and paired; Portal login/MFA remains manual.
A disconnected Bridge cannot distinguish closed Chrome from a disabled/missing
extension. Missing registration, port conflict, timeout and login requirements
have distinct states. Failures expose redacted codes, not raw process output.
Core stdout/stderr are local installation logs in `.cache/desktop-core`, reset
only when the launcher starts a new process; never publish these logs unredacted.
An orphaned startup lock after a Host crash needs local administrator inspection;
the launcher does not guess or kill processes. Bundled Core and repair/log
management remain later work.

Desktop compatibility target: official DeepSeek Harness Desktop `0.2.0-rc.2`
on Windows. This package contributes Host-side **read-only tools** and a
browser-side native **read-only shell** in the sidebar. The business panel
requests a narrow Core/Chrome Bridge connection-status projection through the
Desktop Host. A separate **HKU Admin** panel offers a fixed, read-only Library
facility-catalog test, a SIS connection/course-list/preflight slice, and
four groups of fixed read-only checks for timetable, Moodle, Portal/briefing,
and Library. SIS
course rows are projected for the immediate panel result only; they are not
saved as Admin history. Neither panel exposes F2/F3/F4 write or scheduling
controls. The Desktop UI migration is staged in
`../../HKU_AGENTS_INTEGRATION_PLAN.md` Section 23.8.

Desktop 0.18.10 adds SDK-native pending/completed Chat tool cards with bounded
source/status/count metadata, three business read shortcuts, and a local Admin
history for catalog, SIS sync/preflight and the eleven read operations. The
canonical model result remains available to the Agent; private rows are omitted
from the card metadata and Admin history, not promised absent from Harness Chat
conversation storage. History stores the latest 100 calls in
`%USERPROFILE%\.hku-agents\desktop-test-history-v1.json`, with task/correlation IDs,
safe diagnostic counters/parser version, Host/plugin versions and a separate
human verdict. Core/extension versions are explicitly unknown when not reported.
No inputs, raw error messages, DOM, credentials or private result rows are saved.
History is not a full Core audit viewer and does not import previous calls.
Failed history writes warn without changing the original operation result.
History review writes only local acceptance metadata, never HKU data.
The compact cards do not create booking authority or change the 23 tools.
Consolidated acceptance: `../../docs/DESKTOP_CHAT_ACCEPTANCE.md`.

This package contributes twenty-three restricted HKU tools to DeepSeek Harness:

- `hku_sis_status`
- `hku_sis_navigate_and_preflight` (preferred one-step read-only check)
- `hku_sis_open_enrollment_add_classes`
- `hku_sis_sync_course_lists`
- `hku_sis_preflight`
- `hku_sis_timetable_sync`
- `hku_sis_next_class`
- `hku_sis_find_free_slots`
- `hku_sis_check_timetable_conflicts`
- `hku_sis_exam_status`
- `hku_moodle_inspect_dashboard` (Phase C diagnostics only; no course data)
- `hku_moodle_list_courses` (visible membership only; private rows are process-local)
- `hku_moodle_upcoming_assignments` (bounded visible Dashboard deadlines only)
- `hku_portal_list_notices` (visible Portal News cards; no detail-page navigation)
- `hku_daily_briefing` (cache-only timetable, Moodle deadline, and Portal notice composition)
- `hku_library_research_search` (bounded public Find@HKUL bibliographic search)
- `hku_library_list_facilities` (local verified facility and booking-policy catalog; no browser interaction)
- `hku_library_hours_and_locations` (official public visible hours; unpublished dates remain unknown)
- `hku_library_space_availability` (authenticated visible slots; no booking)
- `hku_library_space_dates` (authenticated live facility Date options; no Search or booking)
- `hku_library_space_booking_preview` (fresh exact-slot and policy preview for five verified categories, including Main Library discussion rooms; no selection or booking)
- `hku_library_research_item` (one fixed record; no full-text navigation)
- `hku_library_research_access_options` (visible access labels; external links suppressed)

It is a thin adapter over the authenticated HKU AGENTS Integration API. It does
not parse HTML, hold browser cookies, choose URLs or selectors, or perform SIS
writes. The Moodle diagnostic tool returns only page-state markers. The course
list tool exposes visible course membership in its current response but excludes
private rows from persistent task history. The upcoming-assignment tool reads only
structured Timeline, Upcoming, and HKU To-do rows for a bounded future window and likewise
does not persist private rows. It does not open activity pages or read grades,
participants, messages, submissions, or submission status. The local HKU AGENTS app and Chrome extension own deterministic Portal
navigation and must be running separately. Login, password entry, CAPTCHA, and
MFA always remain manual. After Portal authentication, Browser Bridge `0.17.1`
may continue through exact allow-listed Portal/Moodle SSO controls automatically;
it never reads or submits credentials and stops for any human authentication
challenge. Moodle tool results report session reuse and SSO navigation separately
from credential and MFA interaction.

The daily briefing never refreshes a source and never interacts with the browser.
Run timetable synchronization, Moodle upcoming assignments, and Portal notice
listing first in the same HKU AGENTS process. Missing, stale, term-mismatched, or
insufficiently covered caches are reported explicitly and their private rows are
omitted.

## Prerequisites

1. Use Node.js `^22.19.0` or `>=24.0.0` for local builds. The verified
   Desktop `0.2.0-rc.2` installation bundles Node `24.18.1`, Cordis `4.0.4`,
   dsh-tools `0.2.0-rc.2`, and Schemastery `3.18.4`; this package pins those
   shared peer versions for that Desktop release.
2. On Windows, enable Developer Mode or run Harness from an elevated terminal.
   Harness uses directory symbolic links while composing profiles; without that
   Windows privilege the CLI can report `EISDIR` before any plugin is loaded.
3. Start HKU AGENTS at `http://127.0.0.1:7860`.
4. On Windows, restart the updated HKU AGENTS service once. It initializes
   `%USERPROFILE%\.hku-agents\connection-v1.json` with current-user DPAPI
   ciphertext for the Integration and Browser Bridge credentials. Core reuses
   these values on later starts when environment overrides are absent.
5. Open Desktop normally from its icon, then click **Connect HKU**. The Host
   reads and decrypts only the Integration credential, bound to its configured
   loopback origin. It asks the paired Chrome extension to detect and bind an
   open HKU tab and shows connected, login-required, missing-tab or Bridge
   states. Existing extension pairing is reused; first-time extension pairing
   still uses the extension popup. HKU login and MFA stay in Chrome.

An explicitly configured `INTEGRATION_API_TOKEN` environment variable remains
an override for advanced/non-Windows use. Ordinary Windows Desktop use needs
no token terminal. Configure the Host `baseUrl` if Core uses another local
port; automatic credentials are never sent to a different origin.

## Local build and test

```powershell
cd integrations/deepseek_harness
npm install
npm test
```

## Install into a Harness profile

For a regular Harness Web profile, from this package directory with the `dsh`
CLI installed:

```powershell
npm run build
npm pack
dsh plugin --profile web add ./dsh-hku-agents-0.18.10.tgz
dsh --profile web --dump-config
dsh --profile web
```

Packing avoids a development-time link from the profile to this source tree.
For a DeepSeek Harness source checkout, use the equivalent `pnpm dsh` commands.
The package declares a `dsh.bundle` whose `cordis.patch.yml` mounts the plugin.

### Official Desktop `0.2.0-rc.2` on Windows

Desktop uses its own `desktop` profile. A Web-profile installation does not
install this plugin into Desktop. First launch Desktop once to initialize its
profile. **Fully quit Desktop**, rather than only closing/hiding its window,
before using the packaged CLI to install a local tarball. In PowerShell, from
this package directory:

```powershell
npm test
npm pack
$dshDesktop = Join-Path $env:LOCALAPPDATA 'Programs\DeepSeek Harness\resources\runtime\cli\bin\dsh.cmd'
& $dshDesktop --version
& $dshDesktop plugin --profile desktop add .\dsh-hku-agents-0.19.2.tgz
& $dshDesktop plugin --profile desktop list
```

The bundled `dsh.cmd` is used because registering `dsh` on PATH is optional.
If Desktop is installed elsewhere, obtain its actual installation path from
the application rather than assuming the path above. Reopen Desktop after the
install and verify the HKU AGENTS status panel, separate HKU Admin entry, and
twenty-three read-only HKU tools. Use **Refresh status** to check Core and Chrome Bridge;
the sidebar appearing by itself does **not**
prove that the local API or Chrome Bridge is connected. The plugin's Node Host
process automatically reads the Windows user's protected local credential
after the updated Core has started once. A manually supplied environment token
still overrides automatic discovery; remove stale overrides when switching to
the ordinary icon-launch workflow. Never put the token value in a plugin
config file, screenshot, or log. The browser-extension pairing token remains
separate and is not decrypted by the Host. If the API or Chrome Bridge is unavailable, the tools must report a
bounded connection error, not attempt a booking.

The `./client` export is a Harness browser-loader module, not a Node or plain
ESM entry point. It uses React and the Desktop connection service, registers
`main` and `sidebar.panellist` through slot injection, and contains no loopback
fetch or credential storage. The business panel requests the exact status
RPC on `/api/hku-agents/status` (`/api` channel, `hku-agents/status` endpoint).
The **Connect HKU** button uses the additional fixed empty-payload
`hku-agents/connect` route, backed by authenticated
`/api/v1/integration/connection/connect`. It binds an existing Chrome tab and
returns only bounded login/page-state fields; it does not read cookies.
The Host uses its existing bearer-authenticated
loopback client, then returns only Core version, bounded Chrome Bridge state,
and a correlation ID; tab URLs, cookies, tokens, and the full Core status are
not sent to the panel. Admin's catalog route is the exact
`/api/hku-agents/admin/facilities` read; it accepts no inputs and returns
only bounded facility labels, locations, support flags, counts and a
correlation ID. Additional fixed SIS routes read the open cart and run live
preflight using only an exact term and at most 20 unique course/section pairs.
The Host bounds and projects Temporary Course List versus Class Schedule rows,
parser counts, preflight verdict and task/correlation IDs. SIS operations never
enroll, alter the cart or save returned course rows as test history. No generic
API console, token, raw DOM, policy body or live booking data is exposed.
Other operations and malformed payloads are rejected.
The `0.18.8` Admin workbench additionally groups eleven fixed read-only cases:
SIS timetable sync and cached next class; Moodle Dashboard, course count and
upcoming-assignment count; Portal notice count and cached Daily Briefing; and
Library hours, live facility Date options, availability count and research
result count. Host routes validate exact fields and project bounded summaries,
write counters, task IDs and correlation IDs. Private course, notice, timetable,
research and exact-slot rows are not sent to this Admin panel. Reading live
Library Date options fills the date input for a separate, explicit availability
test; it does not select a slot or submit Search by itself. Chat's existing
read-only tool results remain available, and the new
`hku_library_space_dates` tool exposes live Date options to Chat. This version
adds compact Chat cards in 0.18.10, but does not yet provide GUI/F1/F2/F3/F4 parity.
The status panel distinguishes an invalid RPC target, missing Host route, protocol
error, and other Host request failure without displaying raw exception text.
These bounded read-only slices are not the full D2 bridge or a Chat/Admin feature-parity
claim. The local Gradio GUI remains the supported operator and recovery UI.

The in-app Plugins manager can also install a local package archive, but this
procedure has not yet been accepted on the user's packaged Desktop build.
Do not use `allow-version` to bypass a compatibility warning: rebuild and
verify against the exact installed release first. Uninstall or rollback should
use the Desktop profile, not the Web profile.

## Configuration

The bundle defaults are:

```yaml
baseUrl: http://127.0.0.1:7860
tokenEnv: INTEGRATION_API_TOKEN
timeoutMs: 45000
```

Override the complete `hku-agents` row in the profile or home
`cordis.patch.yml` when needed. Store only the environment-variable name in
Cordis configuration; do not put the token value in YAML.

## Safety boundary

- Only HTTP(S) loopback hosts (`127.0.0.1`, `localhost`, or `::1`) are accepted.
- Redirects are rejected so the bearer token cannot cross origins.
- Responses are size-limited and must match Integration API v1.
- Harness cancellation is forwarded to the local HTTP request.
- The navigation tool accepts only an exact validated term label. It can follow
  fixed browser-side targets and select that term on the SIS Select Term page.
- The combined tool accepts only an exact term plus the complete expected
  course/section set, automatically binds the available verified Portal tab,
  then composes navigation, structured cart reading, and strict comparison into
  one audited local task.
- Combined results distinguish navigation from enrollment mutation explicitly:
  `navigation_interactions_performed` and `term_selection_performed` are
  booleans, while `enrollment_writes_performed` is always `0`. Zero enrollment
  writes must never be described as zero browser clicks.
- The tool set contains no search, form-fill, add, drop, Step 2/3, enroll, or
  submit command.
