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
| Book a Space availability | ✅ | Partial | Main Library Discussion Room full two-page result read verified; remaining facility routes await per-type live acceptance |
| Book a Space exact booking preview | ✅ | Partial | read-only F1 now supports Discussion Rooms; live exact-slot preview still required |
| Book a Space supervised F2 booking | ✅ | GUI live acceptance pending | opt-in one-shot path; real submission and record/cancellation check require an operator |
| Library facility catalog | ✅ | Partial | 15 allowlisted availability targets; booking preview covers five and F2 writes remain single-room only |
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
The allowlist now includes the Main Library facility types visible in the
user-provided selector screenshot plus the previously verified Chi Wah Study
Room route. Newly added Main Library choices are availability-only until their
live selector labels, eligibility, booking policies, and form behavior are
accepted. A date beyond tomorrow in
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

### F2 supervised one-shot GUI test

The F2 implementation exists, but live write acceptance is still pending. This
test creates a real reservation. Do not run it unless you have chosen a slot you
genuinely intend to use or have first confirmed that the booking can be safely
cancelled through the official **My Booking Record** page. F2 currently accepts
only policy-verified Main Library single study rooms. Eligibility is
self-declared, not checked against account data.

1. Install/reload Browser Bridge `0.17.7`, restart HKU AGENTS, pair the
   extension, and log into the official HKUL booking system in Chrome. Keep
   `APP_HOST` on loopback (`127.0.0.1` by default); F2 refuses drafts otherwise.
2. Keep `LIBRARY_BOOKING_WRITES_ENABLED=false`. In GUI **Library**, search
   availability for `single_study_room` and an exact date equal to today or
   tomorrow in `Asia/Hong_Kong`. Create a booking preview from one exact result
   (floor, room, start, and end). Check that the preview is ready, fresh, and
   exact; its counters must show no selection, form, or booking write.
3. Check the one-reservation policy acknowledgment. Click **1. Prepare one-shot
   action** and confirm its displayed exact target and
   `external_submission_enabled` value. This only creates a GUI action draft;
   it does not yet navigate the booking page or select a slot. Click **2.
   Revalidate action preview**, then read the target and expiry again. Click
   **3. Confirm exact reservation** only after checking those values.
   Revalidation and confirmation do not contact the booking page.
4. For a dry gate test, leave the environment value `false`, then click **4.
   Execute exactly once**. Expected result:
   `LIBRARY_BOOKING_WRITE_DISABLED`, zero browser selection, and zero writes.
   This consumes that action draft; start again with a fresh availability
   preview for any further test.
5. Only for the real supervised test, set
   `LIBRARY_BOOKING_WRITES_ENABLED=true` in the local ignored `project/.env`,
   restart the service, and repeat steps 2-3 to create a fresh preview and
   confirmed draft. Verify the displayed action says
   `external_submission_enabled: true`. Before the last click, verify the exact
   room, date, session, your eligibility category, and policy acknowledgment.
   Clicking **4. Execute exactly once** starts restricted browser interactions:
   it refreshes availability, selects only the exact slot, opens/configures the
   New Booking form, rechecks the target and policy notice, then issues one
   Submit. Click it only if you intend to make that reservation.
6. A successful result must report exactly one Submit, one booking write, and
   `exact_target_verified_in_booking_record: true` with
   `record_match_count: 1`. Open **My Booking Record** yourself and confirm the
   exact row. If the result is `unknown`, the browser disconnects after Submit,
   or the task times out, inspect the record manually and do not retry.
7. Manually cancel the test reservation through HKUL if the official page
   permits it, then verify its cancelled state. F2 does not automate
   cancellation. If cancellation is unavailable or unclear, do not create a
   test reservation; ask for guidance instead.
8. Set `LIBRARY_BOOKING_WRITES_ENABLED=false` again and restart HKU AGENTS.
   The gate should remain off during normal operation.

Retain only the task/correlation IDs, extension version, exact counter values,
record-match verdict, and whether manual cancellation succeeded. Do not paste
pairing tokens, complete authenticated URLs, account identifiers, or raw page
HTML. The F2 action preview returned to the GUI is full for review, but its
exact room/date/time are redacted from persistent action-draft storage.

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
