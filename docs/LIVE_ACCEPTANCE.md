# Live Acceptance Guide

Synthetic tests never contact HKU systems. Live acceptance is the separate step
that verifies a parser and fixed navigation recipe against the user's real,
authorized browser session.

## Current matrix

| Area | Synthetic | Live | Current note |
|---|---:|---:|---|
| Portal→SIS Add Classes | ✅ | ✅ | exact term selection verified |
| SIS cart synchronization/preflight | ✅ | ✅ | match and mismatch cases verified |
| My Weekly Schedule synchronization | ✅ | ✅ | real positioned timetable cards verified |
| Next class/free slots/conflicts | ✅ | ✅ | derived from the same cache snapshot |
| Examination publication status | ✅ | Pending | HKU page was not open for live testing |
| Moodle Dashboard diagnostics | ✅ | ✅ | authenticated Dashboard detection verified |
| Moodle visible courses | ✅ | ✅ | real course cards and deduplication verified |
| Moodle upcoming assignments | ✅ | ✅ | machine-dated To-do/Timeline rows verified |
| Portal visible notices | ✅ | ✅ | titles, dates, source labels, URL redaction verified |
| Daily briefing | ✅ | ✅ | timetable and Moodle caches verified; Portal cache supported |
| Find@HKUL search | ✅ | ✅ | dynamic Primo result rendering verified |
| Find@HKUL item/access options | ✅ | ✅ | stable record and sanitized labels verified |
| Book a Space availability | ✅ | ✅ | color matrix and zero booking writes verified |
| Book a Space exact booking preview | ✅ | Pending | read-only F1 contract implemented; live exact-slot match required |
| Library facility catalog | ✅ | ✅ | four supported policy summaries; Chi Wah Study Room added in F1.1 |
| HKUL hours and locations | ✅ | ✅ | 14 unique live locations; duplicate DOM candidates counted |

## Standard procedure

1. Update and restart the local service.
2. Reload the unpacked extension and confirm its version.
3. Refresh the relevant browser tabs.
4. Log into HKU manually and complete any human authentication prompt.
5. Run the smallest relevant tool through the GUI or Harness.
6. Save the structured JSON result without tokens or complete authentication URLs.
7. Verify the checklist below.
8. If the DOM differs, update synthetic fixtures/tests before changing the parser.
9. Record the accepted parser and bridge versions in the integration plan.

## Universal checklist

- `api_version` is `v1`.
- top-level `ok` reflects task completion, not a business verdict.
- the expected capability ID and task phase are returned.
- `read_only` is true.
- browser/SSO interactions are described accurately.
- every applicable domain-write counter is zero.
- no password, cookie, token, ticket, raw HTML, or unsafe URL appears.
- parser version is current.
- candidate, parsed, duplicate, placeholder, and incomplete counts are plausible.
- an empty result has an explicit verified empty-state or coverage warning.
- persistent task history excludes private row details.

## Enrollment workflow

Precondition: authenticated `studentportal.hku.hk` tab.

Run `hku_sis_navigate_and_preflight` with an exact term and expected
course/section set. Verify:

- navigation steps show Portal→SIS, fixed Add Classes route, and term selection
  only when those interactions actually occurred;
- `term_match` is correct;
- matched, missing, unexpected, and duplicate rows account for the whole cart;
- `enrollment_writes_performed` and `sis_write_requests_sent` are zero;
- no Step 2/3 interaction occurred.

Test both a matching section and a deliberately incorrect section to confirm
that a valid mismatch returns `ok: true`, `ready: false`.

## Timetable workflow

Run timetable synchronization, then `next_class`, `find_free_slots`, and
`check_conflicts`. Verify all derived tools reference the same
`source_fetched_at` and perform no new browser interaction. Compare representative
course cards, weekdays, times, and rooms with the rendered timetable.

## Moodle workflow

Begin with an authenticated Portal tab but a fresh Moodle session. The tool may
activate **HKU Portal user login**. Verify:

- `portal_session_reused` and `sso_interactions_performed` reflect reality;
- `credentials_entered` and `mfa_interactions_performed` remain false;
- course cards have stable Moodle IDs and useful names;
- duplicate carousel/sidebar copies collapse deterministically;
- future assignments fall inside the requested window;
- overdue and beyond-window counts are separate;
- no grade, participant, submission, or message data appears.

## Library workflow

For research search, compare the requested query and visible first-page results.
Open one stable `record_id` through the item and access-options tools. Confirm
that operational UI text and unsafe links are not returned.

For Book a Space, call availability with an exact facility type and
`YYYY-MM-DD` date. Confirm the live selected Location, Facility Type, and Date
match the requested allow-listed target; visible green cells correspond exactly
to returned floor/room/time rows; `result_set_complete` is true; and no slot was
selected. Compare `source_last_updated_at` with the visible page when present.
For the currently supported facility types, a date beyond tomorrow in
`Asia/Hong_Kong` must return `LIBRARY_SPACE_DATE_OUT_OF_WINDOW` before a
booking tab opens. Repeat around Hong Kong midnight to verify the window rolls
over with the local date.
If the page selector exposes more than one page, verify the tool reads each
numbered page, `result_pages_read` equals the displayed page count, and the
returned slots include both pages without duplicates. A failed page switch or
changed filter context must fail closed.
For a day with no available slots, confirm that `slot_candidate_count` is still
positive because booked cells were classified, or that
`verified_empty_result_found` is true. A matrix with zero classifiable cells and
no explicit empty message must fail with
`LIBRARY_SPACE_EMPTY_STATE_UNVERIFIED`, not return a successful empty list.

For `library.spaces.booking_preview`, copy one exact returned slot and confirm
`ready: true`, an exact target, a bounded expiry, a 64-character digest,
`policy_acceptance_recorded: false`, and all selection/form/write counters at
zero. Repeat with a mismatched date and unavailable room; both must return
`ready: false` without creating a preview or performing a write.

F2 must remain disabled during this read-only acceptance. After a successful
preview, an action draft for `library.spaces.book` may be inspected to verify
that it reproduces the exact target, eligibility basis, policy digest, observed
time, and expiry. Do not enable `LIBRARY_BOOKING_WRITES_ENABLED`; the current
executor intentionally stops before any slot selection or Submit action.

For hours, compare every returned location with the current official page. A
live `Today` view must remain described as visible time-period data, not as a
guaranteed weekly schedule. Duplicate responsive DOM copies may increase
`location_candidate_count`; the difference must appear in
`duplicate_location_candidate_count`.

## Evidence to retain

Safe evidence includes:

- correlation and task IDs;
- capability ID;
- bridge/parser versions;
- sanitized origins and page kinds;
- count-only diagnostics;
- zero-write counters;
- redacted screenshots when essential;
- the final acceptance conclusion and date.

Do not retain browser tickets, complete authenticated URLs, bearer/pairing
tokens, cookies, student identifiers, or unnecessary private records.
