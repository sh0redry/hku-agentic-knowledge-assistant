# HKU AGENTS

Local-first HKU student assistant with a visual test workbench, a restricted
browser bridge, a versioned localhost API, and a DeepSeek Harness plugin.

HKU AGENTS reuses the browser session that the user authenticated in Chrome and
turns selected HKU Portal, SIS, Moodle, timetable, and Library pages into
structured agent capabilities. Passwords, cookies, MFA responses, CAPTCHA data,
authentication tickets, and raw private HTML are never exposed to the model.

The original Agentic RAG knowledge assistant remains available as the
`knowledge.answer` capability. HKU integrations are deterministic named tools,
not free-form browser automation.

## Start here

| Goal | Read or run |
|---|---|
| Install HKU AGENTS for the first time | [Deployment and upgrade guide](docs/DEPLOYMENT.md) |
| Pair Chrome or diagnose reconnect/token problems | [Browser Bridge lifecycle](docs/BROWSER_BRIDGE.md) |
| See every capability, input, boundary, and Harness tool | [Capability catalog](docs/CAPABILITIES.md) |
| Understand credentials, private data, and read-only guarantees | [Security and privacy model](docs/SECURITY.md) |
| Verify a release against live HKU pages | [Live acceptance runbook](docs/LIVE_ACCEPTANCE.md) |
| Add or repair a parser/tool | [Development guide](docs/DEVELOPMENT.md) |
| Review delivery phases and deferred work | [Integration plan](HKU_AGENTS_INTEGRATION_PLAN.md) |

## Current status

| Component | Version |
|---|---:|
| Browser Bridge extension | `0.16.1` |
| DeepSeek Harness plugin | `0.16.1` |
| Integration API | `v1` |
| Library research/space parser | `0.2.2` |
| Library hours parser | `0.1.1` |

Implementation and synthetic testing are complete for the capabilities below.
Live acceptance has been completed for Portal-to-SIS enrollment preflight,
weekly timetable synchronization, Moodle Dashboard/course/deadline inspection,
Portal notices, Find@HKUL research search and item details, Library access
options, Book a Space availability, the facility catalog, and HKUL current
opening hours.

### Acceptance snapshot

| Area | Synthetic tests | Live acceptance | Important boundary |
|---|---|---|---|
| SIS enrollment preflight | Complete | Complete | Read cart/schedule only; no enrollment write command |
| Weekly timetable and local derivations | Complete | Complete | Recurring projection; academic-calendar exceptions deferred |
| Examination status | Complete | Blocked by unpublished page | Never converts unpublished data into an empty timetable |
| Moodle courses and deadlines | Complete | Complete | Dashboard-visible scope; no grades, submissions, or participants |
| Portal notices and daily briefing | Complete | Complete | Notice details are not opened |
| Find@HKUL research | Complete | Complete | Licensed full text and account actions are not opened |
| Library spaces and hours | Complete | Complete | Availability is read-only; no slot selection or booking |

This table is a release summary, not a substitute for the evidence checklist in
[the live acceptance runbook](docs/LIVE_ACCEPTANCE.md).

## What it can do

### SIS enrollment checks

- Navigate from an authenticated HKU Portal tab to **Enrollment Add Classes**.
- Select one exact requested term through the verified SIS term page.
- Read the Temporary Course List and current Class Schedule.
- Compare the complete expected course/section set with the live cart.
- Report matched, missing, unexpected, and duplicate entries.

Enrollment mutation is deliberately absent: no course search, delete, Step 2/3,
enroll, drop, or submit command is available.

### Timetable

- Synchronize the live **My Weekly Schedule** page at `sweb.hku.hk`.
- Derive the next class locally from the process-memory cache.
- Find recurring weekly free slots.
- Check candidate meetings for exact time conflicts.
- Inspect examination-publication state when the HKU examination page is open.

Recurring projections do not yet validate teaching weeks, reading weeks, public
holidays, class suspensions, or one-off timetable changes.

### Moodle

- Navigate from Portal to the authenticated Moodle Dashboard.
- Start the exact allow-listed **HKU Portal user login** SSO control when the
  existing Portal session can satisfy it.
- List visible Moodle course membership.
- Read bounded upcoming Dashboard, Timeline, and To-do deadlines.

The bridge never enters credentials or handles MFA. It does not read grades,
participants, messages, submission contents, or submission status, and it never
opens or submits an activity.

### Portal and daily briefing

- Read visible Portal News cards without opening notice detail pages.
- Build a cache-only daily briefing from synchronized timetable, Moodle
  deadlines, and Portal notices.
- Report missing, stale, term-mismatched, and insufficiently covered sources
  independently instead of presenting authoritative empty results.

### HKU Libraries

- Search Find@HKUL with bounded query, field, scope, and result-limit inputs.
- Read a single item using its stable Find@HKUL record ID.
- Return visible online/physical access labels while suppressing proxy, SSO, and
  licensed full-text destinations.
- List supported facilities and verified booking-policy summaries.
- Read visible Book a Space availability for supported fixed facility routes.
- Read locations and visible time-period rows from the official HKUL current
  hours page.

Library tools never select a slot, open a booking form, submit a reservation,
request an item, save a favorite, or open licensed full text. The hours contract
distinguishes explicit `Closed` values from HKUL's “not available yet” state;
unpublished hours are never treated as closures.

## End-to-end workflows

These examples describe what the user sees, which systems are contacted, and
what a successful result means. Exact request bodies and PowerShell examples are
in the [capability catalog](docs/CAPABILITIES.md).

### 1. Portal to SIS enrollment preflight

1. The user signs in to HKU Portal and completes MFA in Chrome.
2. `sis.enrollment.navigate_and_preflight` binds the verified Portal tab,
   follows the fixed SIS route, selects the exact requested term when required,
   and reads the cart.
3. The capability compares the requested course/section set with the complete
   visible Temporary Course List.
4. `ok: true` means the workflow ran correctly; `result.ready` is the separate
   factual match verdict.

Expected audit fields include `navigation_interactions_performed`,
`term_selection_performed`, `sis_write_requests_sent: 0`, and
`enrollment_writes_performed: 0`. Navigation and term selection can involve
clicks even though no enrollment write occurs.

### 2. Weekly schedule to planning answers

1. `sis.timetable.sync_weekly` opens the fixed HKU My Weekly Schedule route and
   stores normalized meetings in process memory.
2. `sis.timetable.next_class`, `find_free_slots`, and `check_conflicts` operate
   locally on that cache and perform no browser interaction.
3. Results include the source timestamp and a warning that recurring meetings
   do not yet account for holidays, reading weeks, or suspensions.

If the cache is missing or stale, synchronize again rather than treating the
absence of cached meetings as an empty schedule.

### 3. Portal SSO to Moodle deadlines

1. The bridge opens Moodle from an authenticated Portal session.
2. If Moodle presents the allow-listed **HKU Portal user login** control, the
   bridge may start that SSO continuation without entering credentials.
3. Password, MFA, CAPTCHA, consent, and recovery prompts remain manual.
4. `moodle.assignments.upcoming` reads only visible Dashboard/Timeline/To-do
   deadline rows inside a bounded time window.

Check `portal_session_reused`, `moodle_session_reused`,
`sso_interactions_performed`, `credentials_entered`, and
`mfa_interactions_performed` to understand what happened. An empty list carries
a coverage warning unless the rendered DOM proves an explicit empty state.

### 4. Find@HKUL research discovery

1. `library.research.search` submits a bounded query through a fixed
   Find@HKUL route and returns normalized visible results.
2. `library.research.item` reads bibliographic metadata for one stable record
   ID.
3. `library.research.access_options` reports safe visible online/physical
   labels without returning authentication-ticket, proxy, or licensed-content
   destinations.

The tool can tell an agent that online access appears available; it does not
open the licensed document, request an item, or access the user's Library
account.

### 5. Library space discovery

1. `library.spaces.list_facilities` returns the supported facility catalog and
   verified policy summary locally.
2. `library.spaces.search_availability` opens the fixed booking availability
   page for a supported facility/date and parses visible available slots.
3. The result must keep `slot_selection_performed: false`,
   `booking_form_opened: false`, and `booking_writes_performed: 0`.

Selecting a slot, previewing a booking, or submitting a reservation is outside
the current phase and would require a separately reviewed write contract.

## Safety model

`read_only: true` means no HKU domain data was changed. It does **not** mean zero
browser interaction. Results explicitly separate navigation, SSO interaction,
data reads, and domain writes.

The Browser Bridge follows these rules:

- exact HTTPS origin allowlists;
- named commands and fixed routes only;
- no arbitrary URL, selector, coordinate, JavaScript, or raw-DOM tool;
- sanitized origin/path reporting with queries and fragments removed;
- no cookie, debugger, download, clipboard, or web-request permission;
- strict Pydantic validation at the local API boundary;
- stable error codes and recovery instructions;
- private timetable, course, assignment, notice, and Library result rows remain
  in process memory and are excluded from SQLite task history;
- writes require separate governance, preview, confirmation, post-condition
  checking, and audit support. No production HKU write capability is enabled.

## Architecture

```text
Authenticated Chrome tab
        │
        ▼
Manifest V3 Browser Bridge
  fixed route + origin parser
        │  paired localhost WebSocket
        ▼
Browser connector ── capability registry ── policy engine
        │                       │
        │                       └── sanitized SQLite task/audit history
        ▼
FastAPI Integration API v1
        ├── Gradio local workbench
        └── DeepSeek Harness plugin
```

The Gradio GUI is the reference local testing, visualization, connection
diagnostics, and recovery environment. External hosts call the same versioned
Integration API rather than controlling Chrome directly.

## Quick start

### Token quick reference

| Secret | Used by | Purpose | Must match |
|---|---|---|---|
| `INTEGRATION_API_TOKEN` | GUI/API clients and DeepSeek Harness | Authorize localhost API calls | HKU AGENTS configuration and host process environment |
| `BROWSER_PAIRING_TOKEN` | Chrome extension | Pair the Browser Bridge WebSocket | HKU AGENTS configuration and extension popup |

Never put either token in prompts, screenshots, committed files, task results,
or issue reports. They must be different random values. See
[deployment](docs/DEPLOYMENT.md) for generation, rotation, and recovery.

### 1. Install Python dependencies

Python 3.11 or newer is recommended.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item project\.env.example project\.env
```

Configure the primary LLM if you want to use the knowledge assistant:

```dotenv
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
DEEPSEEK_API_KEY=your-key
```

Gemini is an optional fallback. Deterministic HKU browser tools do not need an
LLM key, although the host agent invoking them may need its own model setup.

For stable local reconnection, configure two different random values of at least
32 characters:

```dotenv
INTEGRATION_API_TOKEN=replace-with-a-random-host-api-token
BROWSER_PAIRING_TOKEN=replace-with-a-different-random-extension-token
```

The Integration API token is for trusted local agent hosts. The browser pairing
token is only for the Chrome extension. If either is blank, the app creates a
process-local value and displays it in the GUI.

### 2. Start HKU AGENTS

```powershell
python project\app.py
```

Open:

- GUI: `http://127.0.0.1:7860`
- API documentation: `http://127.0.0.1:7860/docs`
- capability inventory: `http://127.0.0.1:7860/api/v1/capabilities`

### 3. Load and pair the Chrome extension

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Choose **Load unpacked** and select `browser_runtime/extension`.
4. Confirm extension version `0.16.1`.
5. Log into HKU Portal manually and complete password/MFA prompts yourself.
6. Copy the browser pairing token from the GUI **Connections** tab into the
   extension popup.

The extension reconnects with bounded backoff. If a configured pairing token is
unchanged, restarting HKU AGENTS does not require pairing again.

## DeepSeek Harness integration

The first-party package exposes 21 restricted HKU tools. It is a thin adapter:
HTML parsing, session state, navigation, privacy filtering, and safety checks
remain inside HKU AGENTS.

Requirements:

- Node.js `^22.19.0` or `>=24.0.0`;
- `pnpm` available to the DeepSeek `dsh` CLI;
- HKU AGENTS running on loopback;
- the same `INTEGRATION_API_TOKEN` exported in the Harness process.

Build, test, and package:

```powershell
cd integrations\deepseek_harness
npm install
npm test
npm pack
```

Install and run:

```powershell
$env:INTEGRATION_API_TOKEN = "the-token-from-project-env-or-the-GUI"
npx.cmd --yes @deepseek-ai/dsh@0.1.2-rc.1 plugin --profile web add .\dsh-hku-agents-0.16.1.tgz
npx.cmd --yes @deepseek-ai/dsh@0.1.2-rc.1 --profile web --dump-config
npx.cmd --yes @deepseek-ai/dsh@0.1.2-rc.1 --profile web
```

See [the Harness plugin README](integrations/deepseek_harness/README.md) for its
complete tool inventory and contract.

## Integration API

All `/api/v1/integration/*` routes require:

```http
Authorization: Bearer <INTEGRATION_API_TOKEN>
X-Correlation-ID: <optional host task ID>
```

Responses use a stable envelope:

```json
{
  "api_version": "v1",
  "ok": true,
  "read_only": true,
  "correlation_id": "host-task-id",
  "result": {},
  "task": null,
  "error": null
}
```

Operation success and domain verdicts are separate. For example, a valid
preflight mismatch is `ok: true` with `result.ready: false`.

| Family | Capability IDs |
|---|---|
| Knowledge | `knowledge.answer` |
| Enrollment | `sis.enrollment.preflight`, `sis.enrollment.live_preflight`, `sis.enrollment.navigate_and_preflight`, `sis.navigation.open_enrollment_add_classes` |
| Timetable | `sis.timetable.sync_weekly`, `sis.timetable.next_class`, `sis.timetable.find_free_slots`, `sis.timetable.check_conflicts`, `sis.timetable.exam_status` |
| Moodle | `moodle.dashboard.inspect`, `moodle.courses.list`, `moodle.assignments.upcoming` |
| Portal/briefing | `portal.notices.list`, `briefing.today` |
| Library research | `library.research.search`, `library.research.item`, `library.research.access_options` |
| Library spaces/hours | `library.spaces.list_facilities`, `library.spaces.search_availability`, `library.hours_and_locations` |

Use `GET /api/v1/capabilities` as the authoritative runtime inventory.

## Testing

The automated suite is synthetic and does not contact HKU systems or perform HKU
writes.

```powershell
# Python platform, API, privacy, and capability tests
python -m unittest discover -s tests -v

# Browser parsers, navigation, target registry, and lifecycle tests
Get-ChildItem tests -Filter *.test.js | ForEach-Object { node.exe $_.FullName }

# Harness TypeScript build and adapter tests
cd integrations\deepseek_harness
npm test
```

Current baseline: 66 Python tests, 9 JavaScript suites, and 14 Harness tests.

Live acceptance is separate: reload the unpacked extension after every Browser
Bridge version change, keep the relevant authenticated HKU tab available, invoke
the exact tool, and inspect parser diagnostics and zero-write counters.

## Project layout

```text
browser_runtime/extension/       Restricted Chrome Browser Bridge
integrations/deepseek_harness/   First-party DeepSeek Harness plugin
project/agents/                  Capability implementations and manifests
project/api/                     FastAPI and Integration API routes
project/browser_bridge/          Pairing, protocol models, session registry
project/connectors/              Browser and simulator connectors
project/services/                Process-local caches and derived services
project/ui/                      Gradio workbench and localhost API client
tests/                           Python and synthetic browser tests
HKU_AGENTS_INTEGRATION_PLAN.md   Roadmap and acceptance history
```

## Privacy and data lifetime

- Browser cookies and credentials stay in Chrome.
- Authentication URLs are reduced to approved origins and paths without query
  strings or fragments.
- Detailed course, timetable, assignment, Portal notice, and Library rows are
  returned immediately but excluded from persistent task history.
- Derived caches are process-memory-only and disappear when the app stops.
- SQLite stores sanitized task state, counters, timestamps, errors, and audit
  metadata in `hku_agents.db` by default.

## Current limitations and roadmap

- Login, password entry, MFA, CAPTCHA, consent, and account recovery remain
  human actions. Allow-listed SSO continuation may reuse an existing Portal
  session without reading credentials.
- Examination timetable live acceptance depends on HKU publishing the page.
- Weekly class projections do not yet incorporate the academic calendar.
- Moodle deadline coverage is limited to rows exposed in the Dashboard DOM and
  does not prove that no other course deadlines exist.
- Library hours reflect the currently rendered HKUL view (for example, `Today`),
  not a guaranteed weekly schedule.
- Library database/guide discovery, Reading Lists, digital collections,
  Scholars Hub, and research-support routing are the next Phase E2 work.
- Space-booking preview and every Library write remain future separately
  governed phases.

See [HKU_AGENTS_INTEGRATION_PLAN.md](HKU_AGENTS_INTEGRATION_PLAN.md) for the full
roadmap and completed live-acceptance checkpoints.

## Troubleshooting

| Symptom | Action |
|---|---|
| `BROWSER_NOT_CONNECTED` | Start HKU AGENTS, open the extension popup, and inspect its retry state. |
| `PAIRING_TOKEN_REJECTED` | Make `BROWSER_PAIRING_TOKEN` match the value stored by the extension, or pair again. |
| `PAGE_SCRIPT_UNAVAILABLE` | Reload the unpacked extension and refresh the relevant HKU page. |
| `PORTAL_LOGIN_REQUIRED` / `SIS_LOGIN_REQUIRED` | Complete the visible HKU authentication flow manually, then retry. |
| `SSO_MANUAL_ACTION_REQUIRED` | Complete the visible password, MFA, CAPTCHA, consent, or recovery step. |
| Parser version mismatch | Reload the extension, refresh the page, and confirm version `0.16.1`. |
| Harness plugin install fails | Install `pnpm`; on Windows, enable Developer Mode or use an elevated shell if profile symlink creation fails. |
| Harness receives `401` | Export the Integration API token, not the browser pairing token. |

## Documentation

| Document | Scope |
|---|---|
| [Deployment and upgrade](docs/DEPLOYMENT.md) | First install, tokens, extension, Harness, upgrades, recovery, removal |
| [Capability catalog](docs/CAPABILITIES.md) | Capability IDs, Harness names, input/output boundaries, examples |
| [Browser Bridge lifecycle](docs/BROWSER_BRIDGE.md) | Pairing, reconnect, tab registry, SSO, commands, stable errors |
| [Security and privacy](docs/SECURITY.md) | Trust boundaries, persistence, URL redaction, fail-closed behavior |
| [Live acceptance](docs/LIVE_ACCEPTANCE.md) | Release matrix, checklists, evidence, workflow-specific acceptance |
| [Development guide](docs/DEVELOPMENT.md) | Full vertical slice, versioning, tests, and live rollout |
| [Integration plan](HKU_AGENTS_INTEGRATION_PLAN.md) | Completed phases, deferred work, and product roadmap |
| [Extension reference](browser_runtime/extension/README.md) | Unpacked-extension setup and implementation details |
| [Harness plugin reference](integrations/deepseek_harness/README.md) | Package-specific installation and tool contract |

`project/README.md` contains historical implementation notes from earlier
iterations. The root README and the documents above are the current operator and
developer references.

## License and project origin

This repository evolved from Agentic RAG for Dummies and retains its
knowledge-retrieval implementation and MIT licensing. HKU AGENTS is an
independent local integration project and is not an official University of Hong
Kong service. Users remain responsible for complying with HKU policies and the
terms of each connected system.
