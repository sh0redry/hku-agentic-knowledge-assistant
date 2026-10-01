# Desktop 0.18.10: one consolidated acceptance session

## Follow-up: Desktop 0.18.12 one-click startup

### Desktop 0.18.14 keyed Chat cards

In a fresh conversation, request live Discussion Room Date options without
booking. Expand Called tools in the Conversation tab: expect an HKU title,
read-only summary, dates/count and available task/correlation identifiers, not
the default input/output JSON pane. View original details should still open the
native inspector. The Trace tab remains unchanged. Historical calls without
metadata may say Result not verified; do not retest previously accepted reads.

Use Desktop 0.18.13 and reload Chrome extension 0.17.22 for the follow-up fixes:
no detached console creation, up to 40 seconds of visible Bridge waiting, and
MV3 alarm-based retry wakeup. If Core was already running, the button reuses it;
this does not exercise the changed process-launch path. Check cold startup on
the next normal Core shutdown/restart, without interrupting real scheduled work.

With Core stopped and paired Chrome open, click **Start and connect HKU**. Expect
background startup followed by Chrome/login checks without a PowerShell window.
With Core running, click again: it must reuse the service, not launch another.
Close Chrome and click again: Core remains connected and Bridge is unavailable.
Reopen Chrome, complete any Portal login/MFA manually, then click **Connect HKU**.
Finally run one live Date read. Do not stop Core if real scheduled work is active.
Port-conflict, invalid-registration and concurrency are automated test cases;
manual simulation is unnecessary for this session.

## Follow-up: Desktop 0.18.11 / Chrome 0.17.21

Reload the Chrome extension and refresh the Moodle Dashboard before repeating
the 14-day deadline Chat request. Duplicate To do/Timeline rows should remain
one deadline, enriched with course metadata where the same event/module and due
time provide a safe match. A course may still be unknown when no visible row
provides it; course-list identifiers alone cannot map an activity to a course.
In Admin, a successful read should display task/correlation IDs only once.
Finish the native Chat-card and restart-history checks below if not yet tested.

Keep Core running, open your paired Chrome profile and authenticate Portal.
Open Desktop normally; use Connect HKU if needed. No token terminal is required.
Previously accepted read-only endpoints need not be retested one by one.

1. In one new Harness conversation, ask three requests in sequence:
   - Synchronize my weekly timetable for `2026-27 Sem 1` and report the next class.
   - Read my visible Moodle deadlines for the next 14 days.
   - Read Main Library Discussion Room's live offered dates without booking.
   Verify a titled pending/completed tool card appears instead of an always-visible
   raw JSON dump. Counts/status, source/cache caveats and available task/correlation
   IDs are shown. The Agent's response may contain private details requested by you;
   compact card metadata must not duplicate private rows. Weekly recurrence is not
   a holiday/teaching-week check. No request authorizes a reservation.
2. In HKU AGENTS, use **Quick read-only checks → Read live facility dates** once.
   Check the dates match the Chat result. Only three shortcuts should be present;
   detailed tests remain in Admin.
3. In HKU Admin, select **Refresh test history**. Expand the new quick-check record,
   confirm parser/correlation information and mark it **pass**. Run one availability
   read with date `2000-01-01` to exercise a safe invalid-date failure. Refresh history:
   the failed read is a separate record, not a zero-slot success. Mark it
   **needs_review**. Restore the live date afterward; no booking is submitted.
4. Exit/reopen Desktop once. Refresh history and verify both records and verdicts
   survived. No private input/search term/room/course/assignment row or raw DOM
   should appear in history. Keep all screenshots redacted and report failures
   together using the task/correlation ID, not a token.

History covers new Admin/quick-check Core calls, not Chat calls, renderer-only
input-validation failures or historical Core tasks. It retains 100 records per
Windows user, not per workspace. Human pass/fail is independent of transport
completion. Corrupt/unwritable history warns and is not silently overwritten.
Full Core audit timeline, arbitrary notes/export and F1/F2/F3/F4 controls remain
later migration work. This batch cannot replace the local booking GUI.

### Moodle Calendar course enrichment (parser 0.4.4 / Chrome Bridge 0.17.23)

Reload the unpacked Chrome extension and reload the Moodle Dashboard. Restart
Core to load the new diagnostic schema; restarting Desktop alone does not restart
Core. No Desktop plugin reinstall is required for this parser-only change.

With the Calendar month cards loaded in the Dashboard DOM, ask Chat once to read
the next 14 days of visible Moodle deadlines, including course attribution.
Compare COMP3278's Entity-Relationship Modeling deadline against Calendar:
course name, date/time, and a single result rather than duplicated rows.
Inspect parser 0.4.4 and `calendar_course_enriched_count`; course_id may remain
null because the supplied Calendar markup contains no numeric course ID.
Calendar labels are matched only by exact event ID, title and deadline instant.
Missing identities, unloaded Calendar cards and conflicting labels are not
guessed; inspect unmatched/conflict counts if course attribution remains unknown.
No popup, activity/submission page, calendar API, month navigation, or write
control is activated by this change. This does not expand deadline coverage.
