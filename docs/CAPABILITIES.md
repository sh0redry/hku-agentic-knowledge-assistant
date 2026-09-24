# Capability and Tool Catalog

`GET /api/v1/capabilities` is the authoritative runtime inventory. This document
adds human-readable intent, host-tool mappings, interaction semantics, and data
boundaries for the current implementation.

## Result semantics

- `ok` describes whether the task completed successfully.
- A domain verdict such as enrollment `ready` is separate from `ok`.
- `read_only` means no domain mutation occurred, not that the browser made no clicks.
- `navigation_interactions_performed` reports controlled browser navigation.
- System-specific write counters remain explicit and fixed at zero for current tools.
- `derived_locally` means the result was calculated without a new browser read.

## Knowledge and status

| Capability | Harness tool | Input | Source and behavior |
|---|---|---|---|
| `knowledge.answer` | — | HKU question | Lazily initialized Agentic RAG knowledge base; low-risk read |
| Integration status | `hku_sis_status` | none | Service, connections, target state, and capability availability; no page mutation |

## Enrollment

| Capability | Harness tool | Input | Browser interaction | Persistent detail |
|---|---|---|---|---|
| `sis.navigation.open_enrollment_add_classes` | `hku_sis_open_enrollment_add_classes` | optional exact term | Portal→SIS, fixed component, optional term selection | navigation summary only |
| `sis.enrollment.live_preflight` | `hku_sis_preflight` | term and expected course/section set | reads already-open cart | counts/verdict; private rows excluded |
| `sis.enrollment.navigate_and_preflight` | `hku_sis_navigate_and_preflight` | term and expected course/section set | complete fixed navigation plus cart read | counts/verdict; private rows excluded |
| SIS synchronization | `hku_sis_sync_course_lists` | none | reads temporary and scheduled course lists | counts only |
| `sis.enrollment.preflight` | — | simulated term/expected/visible rows | none; simulator only | sanitized task result |

Course numbers are read from SIS but are not accepted as live preflight input.
All enrollment write counters remain zero.

## Timetable

| Capability | Harness tool | Input | Source | Notes |
|---|---|---|---|---|
| `sis.timetable.sync_weekly` | `hku_sis_timetable_sync` | exact term | live My Weekly Schedule | updates process-memory cache only |
| `sis.timetable.next_class` | `hku_sis_next_class` | optional term/time/horizon | cache | recurring projection |
| `sis.timetable.find_free_slots` | `hku_sis_find_free_slots` | term, weekdays, window, minimum duration | cache | merges occupied intervals locally |
| `sis.timetable.check_conflicts` | `hku_sis_check_timetable_conflicts` | candidate meeting rows | cache | reports every exact overlap |
| `sis.timetable.exam_status` | `hku_sis_exam_status` | optional term | open SIS examination page | publication state only |

Derived timetable tools set `browser_interactions_performed: false`. Their rows
are based on the most recent process-local synchronization.

## Moodle

| Capability | Harness tool | Input | Data returned | Excluded |
|---|---|---|---|---|
| `moodle.dashboard.inspect` | `hku_moodle_inspect_dashboard` | none | page/auth/parser diagnostics | course and assignment rows |
| `moodle.courses.list` | `hku_moodle_list_courses` | none | visible ID, name, normalized code/section/year/state | grades, participants, submissions |
| `moodle.assignments.upcoming` | `hku_moodle_upcoming_assignments` | bounded `days_ahead` | visible future activity title/type/due time | activity content and submission status |

The tools may navigate from Portal and activate the exact HKU Portal User SSO
entry. Credential and MFA interactions remain false.

## Portal and briefing

| Capability | Harness tool | Input | Behavior |
|---|---|---|---|
| `portal.notices.list` | `hku_portal_list_notices` | none | reads visible Portal News cards; never opens details |
| `briefing.today` | `hku_daily_briefing` | optional term/time/horizon/cache age | cache-only composition of timetable, Moodle, and Portal data |

The briefing never refreshes a source. Call the source synchronization tools
first when fresh coverage is required.

## Library research

| Capability | Harness tool | Input | Browser/data boundary |
|---|---|---|---|
| `library.research.search` | `hku_library_research_search` | query, field, scope, limit | fixed public Primo search; max 20 visible records |
| `library.research.item` | `hku_library_research_item` | stable `record_id` | fixed full-display route; bounded bibliographic metadata |
| `library.research.access_options` | `hku_library_research_access_options` | stable `record_id` | visible availability labels; all external/proxy links suppressed |

These tools never open licensed full text, request an item, save a favorite, or
return an authentication URL.

## Library spaces and hours

| Capability | Harness tool | Input | Interaction and boundary |
|---|---|---|---|
| `library.spaces.list_facilities` | `hku_library_list_facilities` | none | local verified policy catalog; no browser interaction |
| `library.spaces.search_availability` | `hku_library_space_availability` | one supported facility type plus exact `YYYY-MM-DD` date | exact allow-listed Location/Facility Type/Date filters, Search, and complete visible availability read; no slot selection or booking form |
| `library.spaces.booking_preview` | `hku_library_space_booking_preview` | exact date, room, time, optional floor, and self-declared eligibility category | fresh availability match plus short-lived policy preview for single study rooms, editing rooms, study tables, Chi Wah study rooms, and Main Library discussion rooms; no selection, form, authorization, or booking |
| `library.spaces.book` | not exposed to Harness; local GUI only | one process-issued `preview_digest` plus `policy_acceptance_acknowledged: true` | high-risk two-phase confirmation; when `LIBRARY_BOOKING_WRITES_ENABLED=true`, rechecks and submits exactly one Main Library single-study-room target, then verifies one My Booking Record row |
| `library.hours_and_locations` | `hku_library_hours_and_locations` | none | official public hours page; visible location/time-period rows only |

Availability supports the 14 Main Library facility categories visible in the
user-provided selector screenshot, plus the live-verified Chi Wah Learning
Commons `study_room`. Newly added Main Library routes are allowlisted for
read-only availability only until exact labels and facility-specific booking
contracts are verified, except Discussion Room which now also supports a
read-only policy preview. Results expose the selected booking labels,
displayed date, source update timestamp when visible, and result-set
completeness. Dates are limited to today or tomorrow in Hong Kong time before
browser navigation. The bridge reads up to ten numbered result pages, checks
the filters on each page, and fails closed if a page cannot be verified or the
filters change. Listing a facility does not establish current eligibility or
availability.

The read-only booking preview additionally supports Main Library Discussion
Rooms. It enforces the published one-hour interval and reports that the daily
limit, interleaving rule, minimum group size, and account eligibility cannot
be verified from the availability matrix. A live interval that conflicts with
the published session duration is rejected without issuing a preview. F2
submission remains restricted to Main Library single study rooms.

The F2 action envelope stores fresh previews only in process memory, binds the
action draft to the exact target/policy/eligibility facts, rejects expired,
unissued, or previously consumed digests, and uses the platform's one-time
confirmation token. Exact room/date/time values are returned for review but
redacted from persistent action-draft storage. `LIBRARY_BOOKING_WRITES_ENABLED`
defaults to `false`. When enabled by the operator, F2 is available only through
the local GUI, only for Main Library single study rooms, and only after a fresh
availability check and exact form verification. Other facility types require
separate eligibility/policy review, synthetic form fixtures, read-only live
preview acceptance, then an individually scoped F2 live acceptance before
being added. The backend also refuses F2
drafts and execution unless `APP_HOST` is bound to a loopback address. The extension arms a persistent
one-shot execution ID before Submit; an uncertain outcome is terminal and must
be resolved by manually inspecting My Booking Record, never by retrying.

## Host examples

### PowerShell: Library hours

```powershell
$headers = @{
  Authorization = "Bearer $env:INTEGRATION_API_TOKEN"
  "X-Correlation-ID" = [guid]::NewGuid().ToString()
}
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:7860/api/v1/integration/library/hours-and-locations `
  -Headers $headers `
  -ContentType "application/json" `
  -Body "{}"
```

### PowerShell: navigate and preflight

```powershell
$body = @{
  term_label = "2026-27 Sem 2"
  expected_courses = @(
    @{ course_code = "COMP3297"; section = "2B" }
  )
} | ConvertTo-Json -Depth 4

Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:7860/api/v1/integration/sis/navigate-and-preflight `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $body
```

### Natural-language Harness examples

- “Open Enrollment Add Classes for 2026-27 Sem 2 and verify that COMP3297 2B is the complete temporary course list.”
- “Synchronize my 2026-27 Sem 1 weekly timetable, then tell me my next class.”
- “List Moodle assignments due during the next 14 days.”
- “Search Find@HKUL for artificial intelligence and show the first five records.”
- “Read today's visible HKUL opening hours.”

The host model chooses a tool, but the adapter sends only its declared structured
fields. It cannot add a URL, selector, credential, or hidden browser instruction.
