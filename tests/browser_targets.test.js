"use strict";

const assert = require("node:assert/strict");
const targets = require("../browser_runtime/extension/browser_targets.js");

const sanitized = targets.sanitizedLocation(
  "https://studentportal.hku.hk/en-US/?ticket=very-secret#fragment"
);
assert.deepEqual(sanitized, {
  origin: "https://studentportal.hku.hk",
  path: "/en-US/"
});
assert.equal(JSON.stringify(sanitized).includes("very-secret"), false);

assert.equal(targets.classifyUrl("http://moodle.hku.hk/my/"), null);
assert.equal(targets.classifyUrl("https://evil.example/my/"), null);
assert.deepEqual(
  targets.classifyUrl("https://moodle.hku.hk/login/index.php?test=secret"),
  {
    system: "moodle",
    origin: "https://moodle.hku.hk",
    path: "/login/index.php",
    logged_in: false,
    page_kind: "login"
  }
);
assert.equal(
  targets.classifyUrl("https://moodle.hku.hk/my/").page_kind,
  "dashboard"
);
assert.equal(
  targets.classifyUrl(
    "https://julac-hku.primo.exlibrisgroup.com/discovery/account?vid=852JULAC_HKU:HKU"
  ).page_kind,
  "account"
);

const registry = targets.buildRegistry(
  [
    {
      id: 1,
      active: true,
      lastAccessed: 20,
      url: "https://lib.hku.hk/hkulauth/?ticket=secret"
    },
    {
      id: 2,
      active: false,
      lastAccessed: 10,
      url: "https://julac-hku.primo.exlibrisgroup.com/discovery/account?vid=secret"
    },
    {
      id: 3,
      active: true,
      lastAccessed: 30,
      url: "https://sis-main.hku.hk/psp/sisprod/EMPLOYEE/SA/h/?token=secret"
    }
  ],
  3,
  {
    origin: "https://sis-main.hku.hk",
    logged_in: true,
    page_kind: "cart",
    diagnostics: { parser_version: "0.2.2" }
  }
);

assert.deepEqual(registry.map((target) => target.system), ["sis", "library"]);
const sis = registry.find((target) => target.system === "sis");
assert.equal(sis.page_kind, "cart");
assert.equal(sis.parser_version, "0.2.2");
assert.equal(sis.path.includes("?"), false);
assert.equal(sis.safe_for_writes, false);
const library = registry.find((target) => target.system === "library");
assert.equal(library.page_kind, "account");
assert.equal(library.logged_in, true);
assert.equal(JSON.stringify(registry).includes("secret"), false);

console.log("Browser target registry tests passed.");
