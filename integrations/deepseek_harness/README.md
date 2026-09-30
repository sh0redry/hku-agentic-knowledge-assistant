# HKU AGENTS for DeepSeek Harness

Desktop compatibility target: official DeepSeek Harness Desktop `0.2.0-rc.2`
on Windows. This package contributes Host-side **read-only tools** and a
browser-side native **read-only shell** in the sidebar. The business panel
requests a narrow Core/Chrome Bridge connection-status projection through the
Desktop Host. A separate **HKU Admin** panel now offers one fixed, read-only
Library facility-catalog test with a redacted result; it does not show private
capability results. Neither panel
expose F2/F3/F4 write or scheduling controls. The Desktop UI migration is staged in
`../../HKU_AGENTS_INTEGRATION_PLAN.md` Section 23.8.

This package contributes twenty-two restricted HKU tools to DeepSeek Harness:

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
4. In the HKU AGENTS GUI, open **Connections** and copy the Integration API token.
   This is not the browser-extension pairing token.
5. Export the same token in the environment that starts DeepSeek Harness:

   ```powershell
   $env:INTEGRATION_API_TOKEN = "paste-the-local-token-here"
   ```

   Optionally set `HKU_AGENTS_API_BASE_URL` when the local app uses a different
   loopback port. Remote API origins are intentionally rejected.

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
dsh plugin --profile web add ./dsh-hku-agents-0.18.6.tgz
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
& $dshDesktop plugin --profile desktop add .\dsh-hku-agents-0.18.6.tgz
& $dshDesktop plugin --profile desktop list
```

The bundled `dsh.cmd` is used because registering `dsh` on PATH is optional.
If Desktop is installed elsewhere, obtain its actual installation path from
the application rather than assuming the path above. Reopen Desktop after the
install and verify the HKU AGENTS status panel, separate HKU Admin entry, and
twenty-two read-only HKU tools. Use **Refresh status** to check Core and Chrome Bridge;
the sidebar appearing by itself does **not**
prove that the local API or Chrome Bridge is connected. The plugin's Node Host
process must receive the same `INTEGRATION_API_TOKEN` as the HKU AGENTS
service; setting it in a *different* terminal after Desktop has started does
not update that running process. Never put the token value in a plugin config
file, command line, screenshot, or log. The browser-extension pairing token is
separate. If the API or Chrome Bridge is unavailable, the tools must report a
bounded connection error, not attempt a booking.

The `./client` export is a Harness browser-loader module, not a Node or plain
ESM entry point. It uses React and the Desktop connection service, registers
`main` and `sidebar.panellist` through slot injection, and contains no loopback
fetch or credential storage. The business panel requests only the exact status
RPC on `/api/hku-agents/status` (`/api` channel, `hku-agents/status` endpoint).
The Host uses its existing bearer-authenticated
loopback client, then returns only Core version, bounded Chrome Bridge state,
and a correlation ID; tab URLs, cookies, tokens, and the full Core status are
not sent to the panel. Admin's only additional Host route is the exact
`/api/hku-agents/admin/facilities` catalog read; it accepts no inputs and
returns only bounded facility labels, locations, support flags, counts and a
correlation ID. No generic API console, token, policy body or live booking
data is exposed. Other operations and nonempty payloads are rejected.
The status panel distinguishes an invalid RPC target, missing Host route, protocol
error, and other Host request failure without displaying raw exception text.
These two read-only slices are not the full D2 bridge or a Chat/Admin feature-parity
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
