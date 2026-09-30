# F3 Library shadow scheduler

F3.2b is an exact-date, one-time read-only observation mode for HKUL Book a Space. Its
purpose is to let the user evaluate deterministic room/time preferences across
scheduled availability snapshots. It is not an unattended booking feature and
does not grant permission to submit a reservation.

## Hard boundary

For each explicitly dated observation, F3 optionally prepares the facility page,
waits until the configured checking start time, and makes bounded, paced calls to
`library.spaces.list_dates` without submitting Search, then may call
`library.spaces.search_availability` at most once for the exact requested date,
only if that date is live-offered. It does not select a slot,
open a booking form, invoke the F2 action, click Submit/Yes, cancel a booking, or
retry a failed request. The scheduler contains no booking-executor reference.
Every run reports zero booking writes, no slot selection, and no booking-form
opening. A suggestion is informational only; any eventual booking remains a
separate, explicitly confirmed action.

The user specifies the target date, which is checked against the facility's
live Date dropdown at execution. If that exact date is not offered,
the run waits for the next bounded check. Exhausting attempts records
`target_date_not_offered`; reaching the deadline records `observation_window_expired`.
Neither performs an availability Search for a different date.
This accommodates facility-specific holiday skips without maintaining a guessed
holiday calendar. The chosen time is only an observation time. HKUL's actual
release time has not been verified, so F3 does not infer a midnight release or
promise that a slot will remain open. Only Date options are polled, not slots.

## Delivery roadmap (updated 2026-09-27)

- F3.2a live main-path accepted: exact execution date/time, exact use date, full
  preferred intervals, one-time live-date validation, expired-slot filtering and
  migration of old weekday rules.
- F3.2b implemented locally, live release-window acceptance pending: separate preparation, release-check and stop timestamps;
  pre-midnight login preparation; bounded and paced live-date checks after the
  configured release time; visible waiting/querying states and restart handling.
  Example: Sep 28 23:59 preparation, Sep 29 00:00 checking, Sep 30 use date.
- F4 planned: advance authorization for a bounded exact reservation scope,
  fresh execution-time validation, reuse F2 Submit/Yes/success verification,
  at most one successful reservation, and no blind retry of unknown outcomes.
  Start with one accepted facility class after F3 rehearsal and policy review.
- Rule/history cleanup remains a separate planned feature below.

## Requirements and storage

- Windows, with the app running as the same Windows user that created the
  rules. F3 uses current-user DPAPI for rule definitions, room preferences,
  candidate details, and feedback stored in SQLite.
- `APP_HOST` must be loopback-bound (`localhost` or a loopback IP). The F3 API
  also rejects non-loopback clients and is not part of the LLM Integration API.
- The local Browser Bridge must be connected to Chrome, with the authorized
  HKUL booking page/session available at the scheduled time. F3 does not enter
  credentials or complete MFA/CAPTCHA.
- Keep the local app and computer awake through the scheduled observation. A
  run more than two minutes late is recorded as `missed_after_restart`; it is
  not replayed later.

At most five rules can be active at once. Preparation must be within 180 days,
at least 30 seconds ahead when previewing and confirming, and runs exactly once.
Past execution times are rejected, never rolled to tomorrow.
Version-1, version-2 and version-3 active/paused rules are
put in `migration_required` on restart and cannot resume. Review the new
semantics and create a fresh version-4 preview and rule; revoke the old rule.
Completed/revoked history is preserved. Resuming a paused task keeps its original
execution timestamp; if it has passed, create a new reviewed task.
Preparation can start at most 10 minutes before checking. The stop timestamp must
be after checking starts and no more than 10 minutes later. Each interval must
start after the stop timestamp. Blank preparation means start immediately at the
checking timestamp; blank stop means start + 2 minutes. Checks are spaced 15–120
seconds **after the preceding response**, with 1–20 post-start attempts (GUI
defaults: 15 seconds, 8 attempts). These are conservative application limits,
not a claim about HKUL rate limits. Preparation is one additional Date read.
An offered target ends polling; one Search follows, even if it returns no match.
Waiting rules do not block other due rules. F3 browser reads are serialized;
there is no guarantee of exact-second service for simultaneous tasks.
Read errors, including authentication failures, are terminal, not polled retries.
Complete login before the task or during the browser's preparation wait; if it
fails, reconnect/login manually and create a new reviewed task.
Pause/revoke prevents subsequent reads and discards results of an in-flight read.
A read already sent may still finish at the browser after the deadline; its result
is discarded and no Search follows. Restart during preparation/waiting/checking
marks the run interrupted and never replays it.
Reload Chrome's unpacked extension to **0.17.16**. Date checks reuse only an
extension-created date-inspection tab still on the exact availability URL, with
a fresh navigation before each check. Booking forms and unrelated tabs are not reused.
The rule records exact facility type, execution timestamp, target date, ordered room
and full interval preferences, optional fallback behavior, a self-declared
eligibility category, and the run limit. The selected eligibility must be in
the locally published facility catalog. Eligibility is not checked against
the user's HKUL account. Changes to the local verified facility-policy
catalog/version/source contract pause the rule as `policy_changed` before
another availability read; the user must review and create a fresh rule. F3
does not poll public HKUL policy pages, so a real-world change is detected only
after the project's verified local policy catalog is updated. This is one
reason F3 must remain shadow-only and cannot authorize F4.

## GUI workflow

1. Start the local app on Windows, open its Library tab, and refresh the F3
   status. Confirm `enabled: true`, `scheduler_running: true`,
   `booking_authority: false`, and `booking_executor_available: false`.
2. In “Define an exact-date observation,” choose a supported facility, enter the
   facility-use date (`YYYY-MM-DD`) and execution timestamp
   (`YYYY-MM-DD HH:MM:SS`, `Asia/Hong_Kong`), and eligibility category.
   Enter preparation and stop timestamps plus check interval/attempt limits.
3. Add exact room preferences, one per line. Use `FLOOR | ROOM` to bind a floor
   or `ROOM` if the floor is not part of the intended target. Add full intervals
   such as `10:00-11:00, 11:00-12:00` in preferred order. Both start and end must
   match one website slot; intervals are not merged. Already-started slots are excluded.
   Keep the fallback boxes unchecked unless the
   previewed scope should include lower-ranked rooms/times.
4. Click **Preview exact-date shadow task**. Check the exact rule, next run,
   first observation date, maximum run count, policy digest, warnings, and the
   explicit `shadow_only` / no-booking-authority fields. The preview includes
   current Hong Kong time, exact target date and seconds until execution (a
   snapshot at preview time, not a live ticking counter).
5. Check the shadow-only acknowledgment and click **Confirm and create
   shadow-only rule**. This stores a local one-time task; it does not
   touch HKUL at creation time.
6. Refresh status/rules/history. Save the rule ID. Use Pause to stop future
   reads temporarily or Revoke to permanently end the rule. Revoke requires
   its own acknowledgment and cannot be undone.
7. After each scheduled run, refresh run history and compare its ranked
   candidates to what you would actually choose. Enter the run ID and either
   the chosen candidate ID or the “I would book none” choice, then record the
   comparison once. Agreement statistics count only reviewed comparable runs.

### F3.2b short GUI acceptance (no midnight wait needed)

1. Restart the app, reload Chrome extension 0.17.16, reconnect Browser Bridge,
   and log in to HKUL. Refresh the GUI; create a new rule, not a version-3 rule.
2. Use a facility's live offered date and an exact future slot. Set preparation
   to Hong Kong now + 2 minutes, checking start + 3 minutes, stop + 5 minutes;
   set interval 15 seconds and maximum checks 8. All fields use full dates/times,
   without appending the words “Hong Kong”. Preview, review and confirm.
3. At preparation, click Refresh shadow runs: expect `outcome: running`, then
   `phase: waiting_for_start`, `preparation_completed: true`, `date_check_count: 0`.
   There must be no availability Search before the checking start.
4. After start, expect `suggestion_ready` or `no_match` for exactly the requested
   date. A currently offered date normally needs `date_check_count: 1`. All write,
   slot-selection and booking-form counters remain zero/false.
5. Optional bounded-wait check: use a target date absent from live options, set
   maximum checks 2. Expect `waiting_for_date`, then `target_date_not_offered`
   with count 2 and no Search. If stop arrives first, expect `observation_window_expired`.

Midnight rehearsal example (Hong Kong): use date `2026-09-30`, prepare
`2026-09-28 23:59:00`, start `2026-09-29 00:00:00`, stop `2026-09-29 00:02:00`.
Replace these with future dates when testing. No reservation is made by this rehearsal.

There is intentionally no “run now” control. To stop activity immediately,
pause or revoke the rule. Pausing/revoking during an in-flight read causes that
read's candidates to be discarded when it returns.

## Result interpretation

Expected comparable outcomes are:

- `suggestion_ready`: a complete F1 result contained one or more exact
  room/time candidates within the configured preference scope.
- `no_match`: the read completed, but no available slot matched that scope.
- `target_date_not_offered`: the specified date was absent from this facility's
  live Date options; no availability Search was submitted. The requested target
  date is retained in the result; another date is never substituted.
- `authentication_required`: the browser/extension/session required manual
  user action; F3 records the failure and does not retry that occurrence.
- `read_failed` or `unverified_read`: no trusted suggestion was produced.
- `missed_after_restart`: the scheduled observation window was missed; F3
  does not perform a catch-up read.
- `interrupted_after_restart`: the process stopped during a read; treat the
  outcome as unknown and do not infer that a suggestion was generated.

Only `suggestion_ready` and `no_match` can receive human comparison feedback.
Each run accepts one immutable comparison. Candidate IDs are deterministic
within a rule/date/slot, and duplicate room/time rows are collapsed before
ranking. For `no_match`, `availability_slot_count` and `suggestion_reason`
distinguish a genuinely empty availability result from slots that did not match
the configured preference scope.

## Acceptance still required

Local implementation does not equal F3 acceptance. Record at least 20 actual
scheduled runs across the supported facility types, then verify suggestion
and timing agreement against the user's stated choice. The acceptance matrix
must include: no matching slot; disconnected/stale authentication; process
restart before and during an occurrence; pause/revocation before a scheduled
occurrence and during an in-flight read; and a changed local facility-policy digest.
For every run, verify `read_only: true`, zero booking writes, no slot selection,
no booking form, and no call to F2. These observations do not authorize F4.
Any unattended submission requires a separate F0 policy/permission decision
and a separately reviewed F4 design.


### F3 rule and history cleanup (planned 2026-09-27; not implemented)

- Add GUI batch revoke for active/paused rules, and a separate cleanup preview
  for terminal rules and their associated runs, candidates, and comparison feedback.
- Offer explicit scopes: selected rule IDs, terminal history only, or all F3
  rules/history. Preview exact counts and require confirmation before deletion.
- For all-rule cleanup, first revoke ongoing scheduling, cancel/drain in-flight
  observations, and prevent late callbacks from recreating deleted records.
  If quiescence cannot be verified, stop cleanup without deleting history.
- Provide an optional protected export before deletion. Explain that deleting
  reviewed runs changes agreement statistics and removes live acceptance evidence;
  preserve/export acceptance evidence before cleanup.
- Delete related F3 records transactionally with a bounded, redacted cleanup audit
  event. Do not delete the shared database, other modules' tasks/configuration,
  Browser Bridge pairing, or any HKUL reservation.
- Acceptance: cancelled confirmation changes nothing; selected cleanup preserves
  other rules; all-rule cleanup leaves no F3 rules/runs or scheduled work;
  interrupted cleanup rolls back; restart does not restore deleted rules;
  F1/F2/manual queries and creation of new F3 rules continue working.


## Local API

These routes are loopback-only and intended for the local GUI/operator. They
are deliberately separate from `/api/v1/integration/*`:

- `GET /api/v1/library/shadow/status`
- `POST /api/v1/library/shadow/rules/preview`
- `POST /api/v1/library/shadow/rules`
- `GET /api/v1/library/shadow/rules`
- `POST /api/v1/library/shadow/rules/{rule_id}/pause|resume|revoke`
- `GET /api/v1/library/shadow/runs`
- `POST /api/v1/library/shadow/runs/{run_id}/feedback`
