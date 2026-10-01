# Desktop 0.18.9 consolidated acceptance

Use one session to verify automatic connection and the read-only Admin batch.
The previously accepted SIS cart sync/preflight need not be repeated.

Chrome Bridge 0.17.17 continuity check: reload the unpacked extension once,
then run timetable sync, Moodle Dashboard inspection and Portal notice reading
in sequence without manually navigating back to Portal. An authenticated target
tab is reused; if Portal was replaced, a separate fixed Portal entry restores
the session. An actual login/MFA page must still require manual authentication.

1. Keep HKU AGENTS Core running. Open Desktop from its normal icon, without a
   token PowerShell window. Open HKU Portal in the Chrome profile containing
   the already paired HKU AGENTS extension and complete login/MFA if requested.
2. Select **HKU AGENTS → Connect HKU**. Expect Core connected and
   `HKU connected`. If the Bridge is disconnected, open the extension popup
   and select Reconnect; the saved pairing token is reused. If Portal login is
   expired, complete it and select Connect HKU again.
3. Open **HKU Admin → Other read-only interface tests**. Work through the
   groups below in order, waiting for each result before clicking the next.

| Group | Inputs and buttons | Expected result |
| --- | --- | --- |
| SIS timetable | Exact term `2026-27 Sem 1`; Sync weekly timetable → Next class from cache | Meeting count and correct term; next-class found/time or a valid empty result. Weekly projection warning remains visible. |
| Moodle | Inspect Dashboard → Count visible courses → Count upcoming assignments; horizon 14 days | Dashboard ready and counts consistent with the visible Moodle pages. Zero is a valid count. |
| Portal and briefing | Count visible notices → Read cache-based daily briefing | Notice count and explicit source statuses. Missing/stale/partial sources must be shown accurately; they are not successful complete briefing evidence. |
| Library | Select a facility; Read live Date options → review the filled date → Count available slots; Read current hours; enter `artificial intelligence` → Count research results | Live offered dates match Chrome, no invented date; complete availability count; bounded current-hours/research summaries. |

Every completed Admin read must show domain writes 0 and a correlation ID.
Some reads navigate or submit a read-only Search in Chrome. They do not select
booking slots or submit reservations. Admin omits private rows by design.

4. Optionally check Chat once: ask “读取 Main Library Discussion Room 的实时可查询日期，
   不进行预约”. Confirm the Agent uses `hku_library_space_dates` and reports the
   offered dates. This is Chat tool acceptance, not compact-card acceptance.
5. Report all failures together with the group, error code and correlation ID.
   Do not send tokens, cookies or raw authenticated HTML.

First-time extension provisioning still requires pairing in the popup. Native
Messaging and starting Core from the Desktop button are not in this version.
