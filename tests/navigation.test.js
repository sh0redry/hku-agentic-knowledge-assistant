"use strict";

const assert = require("node:assert/strict");
const navigation = require("../browser_runtime/extension/navigation.js");

function link(label, href) {
  return {
    tagName: "A",
    textContent: label,
    clicked: 0,
    getAttribute(name) {
      return name === "href" ? href : null;
    },
    click() {
      this.clicked += 1;
    }
  };
}

function documentWith(elements, bodyText = "Dashboard") {
  return {
    body: { textContent: bodyText },
    querySelector(selector) {
      return selector === "input[type='password']" && bodyText.includes("Password")
        ? {}
        : null;
    },
    querySelectorAll(selector) {
      if (selector === "iframe, frame") return [];
      if (selector === "a, button, [role='link']") return elements;
      return [];
    }
  };
}

const portalLocation = {
  origin: "https://studentportal.hku.hk",
  href: "https://studentportal.hku.hk/dashboard",
  assigned: [],
  assign(url) {
    this.assigned.push(url);
  }
};
const sisEntry = link(
  "Student Information System (SIS)",
  "https://sis-main.hku.hk/sisprod/z_signon.jsp"
);
const portalDocument = documentWith([sisEntry]);
const portalSnapshot = navigation.inspectPortal(portalDocument, portalLocation);
assert.equal(portalSnapshot.page_kind, "portal_home");
assert.equal(portalSnapshot.logged_in, true);
assert.equal(portalSnapshot.navigation_diagnostics.sis_entry_candidate_count, 1);

let queuedPortalNavigation = null;
const portalNavigation = navigation.openSisFromPortal(
  portalDocument,
  portalLocation,
  action => { queuedPortalNavigation = action; }
);
assert.equal(portalNavigation.navigation_only, true);
assert.equal(portalNavigation.sis_write_requests_sent, 0);
assert.equal(portalNavigation.portal_entry_clicked, true);
assert.equal(sisEntry.clicked, 0);
queuedPortalNavigation();
assert.equal(sisEntry.clicked, 1);
assert.deepEqual(portalLocation.assigned, []);

const externalEntry = link("SIS", "https://evil.example/collect");
assert.throws(
  () => navigation.openSisFromPortal(documentWith([externalEntry]), portalLocation),
  error => error.code === "NAVIGATION_TARGET_NOT_FOUND"
);

assert.throws(
  () => navigation.openSisFromPortal(documentWith([], "Log in with UID Password"), portalLocation),
  error => error.code === "PORTAL_LOGIN_REQUIRED"
);

const sisLocation = {
  origin: "https://sis-main.hku.hk",
  href: "https://sis-main.hku.hk/psc/sis",
  assigned: [],
  assign(url) {
    this.assigned.push(url);
  }
};
const sisDocument = documentWith([], "SIS Menu Enrollment Add Classes");
const inspectSis = () => ({ logged_in: true, page_kind: "home" });
let queuedSisNavigation = null;
const sisNavigation = navigation.openEnrollmentAddClasses(
  sisDocument,
  sisLocation,
  inspectSis,
  action => { queuedSisNavigation = action; }
);
assert.equal(sisNavigation.navigation_started, true);
assert.equal(sisNavigation.target_origin, "https://sis-main.hku.hk");
assert.equal(sisLocation.assigned.length, 0);
queuedSisNavigation();
assert.match(sisLocation.assigned[0], /SA_LEARNER_SERVICES\.SSR_SSENRL_CART\.GBL/);
assert.match(sisLocation.assigned[0], /FolderPath=PORTAL_ROOT_OBJECT\.Z_SIS_MENU\.Z_ENROLLMENT/);

const termRow = { textContent: "2026-27 Sem 2 Undergraduate Career" };
const termRadio = {
  clicked: 0,
  labels: [],
  getAttribute() { return null; },
  closest(selector) { return selector === "tr" ? termRow : null; },
  click() { this.clicked += 1; }
};
const continueButton = {
  textContent: "Continue",
  clicked: 0,
  getAttribute() { return null; },
  click() { this.clicked += 1; }
};
const termDocument = {
  body: { textContent: "Select Term Select a term then select Continue. 2026-27 Sem 2" },
  querySelector() { return null; },
  querySelectorAll(selector) {
    if (selector === "iframe, frame") return [];
    if (selector === "input[type='radio']") return [termRadio];
    if (selector === "button, input[type='button'], input[type='submit'], a") {
      return [continueButton];
    }
    return [];
  }
};
let queuedTermNavigation = null;
const termNavigation = navigation.selectTerm(
  termDocument,
  sisLocation,
  "2026-27 Sem 2",
  () => ({ logged_in: true, page_kind: "term_selection" }),
  action => { queuedTermNavigation = action; }
);
assert.equal(termNavigation.selected_term_label, "2026-27 Sem 2");
assert.equal(termNavigation.sis_write_requests_sent, 0);
assert.equal(termRadio.clicked, 0);
queuedTermNavigation();
assert.equal(termRadio.clicked, 1);
assert.equal(continueButton.clicked, 1);

assert.throws(
  () => navigation.selectTerm(
    termDocument,
    sisLocation,
    "2026-27 Sem 1",
    () => ({ logged_in: true, page_kind: "term_selection" })
  ),
  error => error.code === "TERM_NOT_AVAILABLE"
);

assert.deepEqual(
  navigation.openEnrollmentAddClasses(sisDocument, sisLocation, () => ({
    logged_in: true,
    page_kind: "cart"
  })),
  { navigation_started: false, already_at_target: true }
);

console.log("Restricted HKU navigation synthetic tests passed.");
