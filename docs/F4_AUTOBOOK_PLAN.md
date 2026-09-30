# F4 scheduled booking — staged delivery plan

F4 is a separate delegated-write feature, not an upgrade of F3's shadow-only
rules or F2's short-lived confirmation token. No existing F3 rule grants booking
authority. The first pilot is restricted to one exact Main Library / Level 3
Discussion Room, one exact use date and one exact one-hour session, with no room
or time fallback and at most one successful booking.

## Stage 0 — delivered locally: scope preview and GUI organization

- The Library GUI separates Research & hours, Space availability, Exact preview,
  supervised F2, shadow F3 and scheduled F4 into distinct tabs. Availability and
  exact-preview results stay visible in their own tabs. F1–F3 handlers and
  authorization boundaries are unchanged.
- The F4 tab provides only a local design preview for the narrow pilot scope.
  It validates Hong Kong preparation/check/stop timestamps, exact target/date,
  session, declared eligibility and bounded Date checks. It displays a local
  verified-policy digest and unresolved gates. It creates no preview token,
  standing authorization, browser task, reservation or booking executor path.
- The pilot preview is loopback-only and read-only. F2's write gate cannot
  enable unattended submission; F3 shadow rules cannot be upgraded in place.

## Stage 1 — gates before delegated writes

1. Automation permission remains unverified and is not an engineering release
   gate at the user's direction. Do not represent it as approved; continue to
   enforce the facility's published eligibility and booking limits.
2. Accept at least one F3.2b live transition where the target date is absent
   before checking starts and appears during the bounded window. Verify observed
   release behavior for each pilot facility; do not infer midnight as universal.
3. Verify the account's existing bookings and eligibility, and an authoritative
   My Booking Record exact-match read. The F2 success dialog alone is not
   sufficient as F4's postcondition.

## Stage 2 — standing authorization, without external submission

- Add a separate DPAPI-protected `StandingAuthorization` store, preview and
  explicit confirmation. Bind local user, capability version, exact date,
  location/floor/room, one session, preparation/check/stop window, policy digest,
  eligibility declaration, one-success limit and absolute expiry. Any change
  requires a fresh preview and confirmation.
- Add list/pause/revoke, visible countdown/status, immutable audit events and a
  one-shot occurrence ledger. Revocation must be checked before browser activity
  and immediately before any Submit.
- Exercise creation, pause, revoke, restart and privacy with fake browser tasks;
  do not expose submission until Stage 1 gates and Stage 2 tests pass.

## Stage 3 — gated one-shot executor and acceptance

- Reuse F2's verified exact-slot/form/Submit/Yes browser contract only through a
  distinct F4 internal executor. Freshly read live dates and availability,
  revalidate authorization and policy, check the account's current booking
  limit, then select one exact candidate. No automatic cancellation.
- Submit at most once. Ambiguous post-Submit results become
  `BOOKING_OUTCOME_UNKNOWN`, freeze that authorization and require manual My
  Booking Record reconciliation; no blind retry. Report success only after
  exactly one authoritative matching record.
- Stop on login/MFA/CAPTCHA, unknown page state, rate limiting or policy change.
  Keep bounded, paced checks; no parallel tabs or anti-bot bypass.
- Begin with a separately approved low-impact live pilot for one facility class,
  one authorization and one reservation. Expanding classes requires separate
  policy, DOM and live acceptance.

## Current checkpoint: inert draft flow delivered

The F4 tab now offers a short-lived, single-use draft preview digest, explicit
acknowledgement, DPAPI-protected local draft storage, list and one-way revoke.
These records have state `held_non_authorizing`, no scheduler occurrence, no
browser interaction, and no booking authority. Restarting the app does not
turn them into standing authorizations. A fresh, separate confirmation will be
required before an executor is enabled. Automation permission remains
unverified but is not an engineering gate at the user's direction. F3.2b live
release-transition acceptance and authoritative account/record checks remain
open; unattended Submit is not enabled.

## Current checkpoint: separate one-time authorization record

F4 now also has its own short-lived preview and three explicit acknowledgements
for a single exact future booking attempt. The protected authorization stores
target, policy digest, one-success limit and absolute expiry separately from
inert drafts and F3 rules. Its only current state is `pending_executor`; it can
be paused or irrevocably revoked. No scheduler reads these authorizations, no
`next_run_at` is set, and no browser or Submit path is connected. Creation and
restart do not execute a booking. A transactionally single-use internal attempt
ledger is implemented but is not exposed through any API or scheduler. Once an
attempt is claimed it remains outcome-unknown until exactly one authoritative
record resolves it; a second claim is rejected.

No stage authorizes a real booking merely because this document, a chat message
or an F3 suggestion exists. The F4 authorization preview must be reviewed and
explicitly confirmed in the GUI; the resulting record remains non-executable
until a guarded executor is separately implemented and tested.
