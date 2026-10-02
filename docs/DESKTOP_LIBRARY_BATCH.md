# Desktop Library F1–F4 consolidated batch

Release: Harness plugin **0.19.0**, Chrome Bridge **0.17.24**, booking-form/record
parser **0.1.3**. Implementation is ready for consolidated acceptance, not a
claim of real HKUL acceptance. Development made no real reservations.

Verification: 144 Python project tests, 56 Desktop plugin tests and all 12
browser synthetic regression scripts pass. Existing asyncio/resource and
Starlette deprecation warnings remain; no failures were hidden. Versioned npm
archive: `integrations/deepseek_harness/dsh-hku-agents-0.19.0.tgz` (48 files).
Plugin 0.19.0 is installed in the Desktop profile after user approval. Core was
started with F2 submission disabled and F4 runtime disabled (dry-run default);
both states were verified through the authenticated operator API. No booking
gate was enabled. Live HKUL acceptance remains pending.

## Delivered

- Authenticated loopback-only fixed operator RPC, typed inputs, Host-only
  credentials and bounded business projections. No generic HTTP/script proxy.
- Business and Admin have separate F1/F2/F3/F4 workflows. The existing 23 Chat
  tools remain read-only; no model-callable booking-write tool was added.
- F1: live Date options, exact availability and expiring preview.
- F2: policy/rule review, exact action draft, explicit single submission and
  task/result polling. Admin can explicitly change its process-only write gate;
  changing the gate invalidates existing previews. Never automatically retry.
- F3: exact-date preparation/check/stop windows, bounded Date polling,
  preferences/fallback, rules/runs/feedback and pause/resume/revoke.
- F4: protected version-2 advance authorization, separately reviewed runtime
  enablement and exact arming, one armed pilot authorization, bounded Date
  polling, fresh exact availability, account-record preflight, verified form and
  durable single-use claim before Submit. Browser checks deadline before Submit
  and before accepting the site confirmation.
- F4 dry run reads only: no slot selection, booking form or Submit. An armed dry
  run cannot switch to live. A finished dry run requires a new authorization.
- F4 success requires one exact My Booking Record match including location,
  floor, room, date and interval. A success dialog alone is insufficient.
- Transport loss after claim is terminal `outcome_unknown`, never zero writes
  and never automatically retried. Pause/revoke cannot undo dispatched Submit.
- Restart disables F4 runtime; interrupted preparation is not replayed and a
  claimed attempt stays unknown. Desktop closure alone does not stop Core.
- History stores redacted stage/outcome/IDs, not targets, inputs, tokens or DOM.
  Request completion is not booking success. Gradio remains a recovery fallback.

## Deliberately narrow F4 scope

Main Library / Level 3 / one exact Discussion Room / one 60-minute interval,
no fallback, only execution-day or next-day facilities, still checked against
live Date options. Preparation is up to 10 minutes before checks; stop is within
10 minutes after checks. Poll interval 15–120 seconds, maximum 1–20 checks.
The worker wakes approximately once a second, not a hard-real-time guarantee.

The target day must be **verifiably empty in the account's booking records**.
Existing bookings, partial/paginated records or unknown row shapes stop the
attempt; this pilot does not calculate remaining quota/interleaving from partial
records. Eligibility and minimum group size remain user-attested, not account-
category verified. Policy drift checks the local verified catalog, not live
policy pages. Automated-use permission is not an engineering gate per user
direction. Real midnight release behavior must still be observed.

## One consolidated acceptance session

1. Fully exit Desktop for installation. Restart Core only when no booking is in
   flight; reload extension 0.17.24 and refresh HKU tabs. Reopen Desktop and
   Start/connect without a token terminal. Login/MFA remains manual.
2. F1/F2: choose a live offered date and available exact interval, read and
   preview. Keep F2's gate off; prepare and confirm only as a gate-refusal test.
   Expect disabled gate and no reservation. Edit the target: old preview must
   become unusable. Optional real F2 acceptance needs Admin gate enablement,
   fresh preview/draft/exact confirmation for a reservation the user wants.
3. F3: create one short exact-date shadow task. Refresh runs after completion,
   compare exact candidate/no-match, verify zero writes. Review feedback and
   pause/revoke in the same session without repeated real reservations.
4. F4: Admin enables dry run explicitly. Preview/create a new authorization,
   list/select it, review the displayed exact target and all acknowledgments,
   then arm. After checking time refresh authorizations. Expected success:
   `dry_run_ready_no_submission`, attempt_count=0, writes=0, no form/slot selection.
   Actual refusal is not a pass: record its error code. Refresh again to verify
   no re-run, then disable runtime. Incomplete record parsing needs a sanitized
   row/header fixture, never full DOM, cookies or account identifiers.
5. Optional real F4 acceptance: a separate new future authorization, live mode,
   exact arming and a verified empty target day are required. Do not promote a
   dry run or legacy record. Inspect My Booking Record; if unknown, stop and
   reconcile manually rather than repeating Submit. Real F2/F4 writes and a
   midnight Date transition remain pending until actually accepted.

Automated tests cover double-click, concurrent ticks, expiry, target/policy
drift, disabled/unarmed state, record incompleteness, duplicate record matches,
pause during preparation, crash after claim and ambiguous transport.
