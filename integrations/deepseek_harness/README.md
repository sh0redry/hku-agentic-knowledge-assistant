# HKU AGENTS for DeepSeek Harness

This package contributes thirteen restricted HKU tools to DeepSeek Harness:

- `hku_sis_status`
- `hku_sis_navigate_and_preflight` (preferred one-step read-only check)
- `hku_sis_open_enrollment_add_classes`
- `hku_sis_sync_course_lists`
- `hku_sis_preflight`
- `hku_sis_timetable_sync`
- `hku_sis_next_class`
- `hku_sis_find_free_slots`
- `hku_sis_check_timetable_conflicts`
- `hku_sis_exam_status`
- `hku_moodle_inspect_dashboard` (Phase C diagnostics only; no course data)
- `hku_moodle_list_courses` (visible membership only; private rows are process-local)
- `hku_moodle_upcoming_assignments` (bounded visible Dashboard deadlines only)

It is a thin adapter over the authenticated HKU AGENTS Integration API. It does
not parse HTML, hold browser cookies, choose URLs or selectors, or perform SIS
writes. The Moodle diagnostic tool returns only page-state markers. The course
list tool exposes visible course membership in its current response but excludes
private rows from persistent task history. The upcoming-assignment tool reads only
machine-dated Timeline/Upcoming rows for a bounded future window and likewise
does not persist private rows. It does not open activity pages or read grades,
participants, messages, submissions, or submission status. The local HKU AGENTS app and Chrome extension own deterministic Portal
navigation and must be running separately. Login, password entry, CAPTCHA, and
MFA always remain manual.

## Prerequisites

1. Use Node.js `^22.19.0` or `>=24.0.0`, matching the current Harness runtime.
2. On Windows, enable Developer Mode or run Harness from an elevated terminal.
   Harness uses directory symbolic links while composing profiles; without that
   Windows privilege the CLI can report `EISDIR` before any plugin is loaded.
3. Start HKU AGENTS at `http://127.0.0.1:7860`.
4. In the HKU AGENTS GUI, open **Connections** and copy the Integration API token.
   This is not the browser-extension pairing token.
5. Export the same token in the environment that starts DeepSeek Harness:

   ```powershell
   $env:INTEGRATION_API_TOKEN = "paste-the-local-token-here"
   ```

   Optionally set `HKU_AGENTS_API_BASE_URL` when the local app uses a different
   loopback port. Remote API origins are intentionally rejected.

## Local build and test

```powershell
cd integrations/deepseek_harness
npm install
npm test
```

## Install into a Harness profile

From the repository root, with the `dsh` CLI installed:

```powershell
cd integrations/deepseek_harness
npm run build
npm pack
dsh plugin --profile web add ./dsh-hku-agents-0.6.0.tgz
dsh --profile web --dump-config
dsh --profile web
```

Packing avoids a development-time link from the profile to this source tree.
For a DeepSeek Harness source checkout, use the equivalent `pnpm dsh` commands.
The package declares a `dsh.bundle` whose `cordis.patch.yml` mounts the plugin.

## Configuration

The bundle defaults are:

```yaml
baseUrl: http://127.0.0.1:7860
tokenEnv: INTEGRATION_API_TOKEN
timeoutMs: 45000
```

Override the complete `hku-agents` row in the profile or home
`cordis.patch.yml` when needed. Store only the environment-variable name in
Cordis configuration; do not put the token value in YAML.

## Safety boundary

- Only HTTP(S) loopback hosts (`127.0.0.1`, `localhost`, or `::1`) are accepted.
- Redirects are rejected so the bearer token cannot cross origins.
- Responses are size-limited and must match Integration API v1.
- Harness cancellation is forwarded to the local HTTP request.
- The navigation tool accepts only an exact validated term label. It can follow
  fixed browser-side targets and select that term on the SIS Select Term page.
- The combined tool accepts only an exact term plus the complete expected
  course/section set, automatically binds the available verified Portal tab,
  then composes navigation, structured cart reading, and strict comparison into
  one audited local task.
- Combined results distinguish navigation from enrollment mutation explicitly:
  `navigation_interactions_performed` and `term_selection_performed` are
  booleans, while `enrollment_writes_performed` is always `0`. Zero enrollment
  writes must never be described as zero browser clicks.
- The tool set contains no search, form-fill, add, drop, Step 2/3, enroll, or
  submit command.
