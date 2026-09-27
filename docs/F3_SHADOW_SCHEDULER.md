# F3 Library shadow scheduler

F3 is a recurring, read-only observation mode for HKUL Book a Space. Its
purpose is to let the user evaluate deterministic room/time preferences across
scheduled availability snapshots. It is not an unattended booking feature and
does not grant permission to submit a reservation.

## Hard boundary

For each daily scheduled observation, F3 first calls
`library.spaces.list_dates` without submitting Search, then may call
`library.spaces.search_availability` at most once for a live-offered date matching
the target weekdays. It does not select a slot,
open a booking form, invoke the F2 action, click Submit/Yes, cancel a booking, or
retry a failed request. The scheduler contains no booking-executor reference.
Every run reports zero booking writes, no slot selection, and no booking-form
opening. A suggestion is informational only; any eventual booking remains a
separate, explicitly confirmed action.

The target date is selected from the exact facility's live Date dropdown at
the daily observation time. If no offered date matches the rule's weekdays,
the run records `target_date_not_offered` and performs no availability Search.
This accommodates facility-specific holiday skips without maintaining a guessed
holiday calendar. The chosen time is only an observation time. HKUL's actual
release time has not been verified, so F3 does not infer a midnight release,
poll, or promise that a slot will remain open.

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

At most five rules can be active at once. Rules expire after 180 days and
support at most 20 scheduled occurrences each.
Version-1 rules created under the former preceding-calendar-day schedule are
put in `migration_required` on restart and cannot resume. Review the new
semantics and create a fresh version-2 preview and rule; revoke the old rule.
The rule records exact facility type, weekdays, time zone/time, ordered room
and start-time preferences, optional fallback behavior, a self-declared
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
2. In “Define a narrow observation rule,” choose one F1-preview-supported
   facility type. Select the target weekday(s), observation time in
   `Asia/Hong_Kong`, a catalog-supported eligibility category, and a maximum
   of 20 occurrences.
3. Add exact room preferences, one per line. Use `FLOOR | ROOM` to bind a floor
   or `ROOM` if the floor is not part of the intended target. Add exact start
   times in preferred order. Keep the fallback boxes unchecked unless the
   previewed scope should include lower-ranked rooms/times.
4. Click **Preview recurring shadow rule**. Check the exact rule, next run,
   first observation date, maximum run count, policy digest, warnings, and the
   explicit `shadow_only` / no-booking-authority fields.
5. Check the shadow-only acknowledgment and click **Confirm and create
   shadow-only rule**. This stores a local recurring read rule; it does not
   touch HKUL at creation time.
6. Refresh status/rules/history. Save the rule ID. Use Pause to stop future
   reads temporarily or Revoke to permanently end the rule. Revoke requires
   its own acknowledgment and cannot be undone.
7. After each scheduled run, refresh run history and compare its ranked
   candidates to what you would actually choose. Enter the run ID and either
   the chosen candidate ID or the “I would book none” choice, then record the
   comparison once. Agreement statistics count only reviewed comparable runs.

There is intentionally no “run now” control. To stop activity immediately,
pause or revoke the rule. Pausing/revoking during an in-flight read causes that
read's candidates to be discarded when it returns.

## Result interpretation

Expected comparable outcomes are:

- `suggestion_ready`: a complete F1 result contained one or more exact
  room/time candidates within the configured preference scope.
- `no_match`: the read completed, but no available slot matched that scope.
- `target_date_not_offered`: the exact facility's live Date options included no
  new target weekday; no availability Search was submitted.
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
