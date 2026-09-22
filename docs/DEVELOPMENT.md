# Development Guide

This guide describes the repository's preferred vertical-slice workflow for
adding or changing an HKU capability.

## Design rule

Do not add general browser automation. Every browser-backed capability must be a
named, origin-bound, state-checked operation with structured input and output.

## Vertical-slice sequence

```text
authorized page observation
  → origin and page-kind contract
  → deterministic content parser
  → named extension command
  → typed browser message model
  → connector method
  → capability and persistence projection
  → Integration API endpoint
  → GUI control
  → Harness tool
  → synthetic tests
  → live acceptance
  → plan/checkpoint update
```

## 1. Observe safely

Use an authorized browser session and record only what is necessary to define
the DOM contract. Prefer screenshots, labels, counts, and sanitized fixtures.
Never copy cookies, SSO tickets, complete authenticated URLs, raw private HTML,
or unrelated student records into the repository.

Identify:

- exact allowed origin and fixed path;
- login, error, loading, ready, empty, and unpublished states;
- stable semantic markers rather than visual coordinates;
- duplicate responsive/mobile/hidden DOM copies;
- values that are machine-readable versus inferred from display text;
- every interaction needed before the read;
- every control that must remain unavailable.

## 2. Add target classification

Update `browser_runtime/extension/browser_targets.js` only for approved origins
and page kinds. Target status must expose a sanitized path without query or
fragment data. Add a synthetic registry/classification test.

## 3. Implement the parser

Place parsing logic in the origin-specific parser module. Parsers should:

- accept a document and location object;
- reject the wrong origin/path;
- normalize bounded structured fields;
- expose parser version and count-only diagnostics;
- identify explicit empty/unpublished states;
- count incomplete, unsafe, duplicate, and placeholder candidates;
- avoid returning raw HTML or unknown links;
- behave deterministically on synthetic fixtures.

When omission could alter a verdict, fail closed instead of returning a partial
success. If the page's coverage is inherently limited, return a clear warning.

## 4. Add the named command

Update `library_content.js`, `moodle_content.js`, or the appropriate content
listener, then add one explicit command in `background.js`. The background
implementation owns the fixed URL, target selection, polling deadline, stable
ready signature, and navigation metadata.

Never accept a caller-supplied URL, selector, script, or coordinate.

## 5. Define protocol models

Add strict Pydantic models in `project/browser_bridge/models.py` and a command
enum entry in `project/connectors/sis/protocol.py`. Models should use literals,
bounds, regexes, validators, and exact count relationships wherever possible.

The connector in `project/connectors/sis/browser.py` must validate every
extension response before a capability sees it.

## 6. Implement the capability

Capabilities live under `project/agents/` and declare:

- ID, title, description, mode, risk, and confirmation behavior;
- required connections and availability;
- input/output schema names and timeout;
- parser-version expectation;
- fail-closed semantic checks;
- explicit interaction/read/write counters;
- `persisted_input` and `persisted_result` privacy projections.

Register the capability in `project/application.py`.

## 7. Expose clients

Add the Integration API route in `project/api/integration.py`, including stable
recovery guidance. Then add matching GUI client/handler/control code under
`project/ui/`.

For Harness, update:

- `integrations/deepseek_harness/src/client.ts`;
- `integrations/deepseek_harness/src/index.ts`;
- package/readme versions when required;
- adapter tests and generated `lib/` output.

Tool descriptions must state whether navigation, SSO, private reads, or domain
writes occur. Do not describe zero writes as zero clicks.

## 8. Versioning

- Parser contract or live DOM fix: bump that parser's patch/minor version.
- New/changed extension command or content contract: bump Browser Bridge version.
- New/changed Harness tool or description contract: bump npm package version.
- Breaking Integration API envelope change: create a new API version rather than
  silently changing `v1`.

Update every version expectation and recovery message together.

## 9. Test

Minimum coverage for a new browser-backed read:

- successful parser fixture;
- wrong origin/path rejection;
- loading or not-ready state;
- explicit empty/unpublished state where applicable;
- duplicate/incomplete/unsafe candidate behavior;
- strict Pydantic validation;
- capability success and failure;
- privacy-persistence assertion;
- zero-write counters;
- API authentication and stable envelope;
- GUI wiring;
- Harness tool inventory and exact forwarded body;
- target classification and URL redaction.

Run:

```powershell
python -m unittest discover -s tests -v
Get-ChildItem tests -Filter *.test.js | ForEach-Object { node.exe $_.FullName }
cd integrations\deepseek_harness
npm test
```

## 10. Live acceptance

Synthetic success is not production acceptance. Follow
[LIVE_ACCEPTANCE.md](LIVE_ACCEPTANCE.md), compare the result with the rendered
page, harden diagnostics if necessary, and record the accepted versions and
evidence in [`HKU_AGENTS_INTEGRATION_PLAN.md`](../HKU_AGENTS_INTEGRATION_PLAN.md).

## Working-tree discipline

Existing changes belong to the user unless clearly created by the current task.
Avoid destructive Git commands and unrelated rewrites. Use targeted patches,
run `git diff --check`, and report which tests were executed.
