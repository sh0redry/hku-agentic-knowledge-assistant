(function (root) {
  "use strict";

  const SYSTEM_ORDER = ["portal", "sis", "moodle", "library"];
  const TARGET_PATTERNS = [
    "https://hkuportal.hku.hk/*",
    "https://studentportal.hku.hk/*",
    "https://sis-main.hku.hk/*",
    "https://moodle.hku.hk/*",
    "https://julac-hku.primo.exlibrisgroup.com/*",
    "https://lib.hku.hk/*"
  ];

  function sanitizedLocation(value) {
    try {
      const parsed = new URL(value);
      if (parsed.protocol !== "https:") return null;
      return { origin: parsed.origin, path: parsed.pathname || "/" };
    } catch (_error) {
      return null;
    }
  }

  function classifyUrl(value) {
    const location = sanitizedLocation(value);
    if (!location) return null;
    const path = location.path.toLowerCase();
    if (["https://hkuportal.hku.hk", "https://studentportal.hku.hk"].includes(location.origin)) {
      const login = path.includes("login") && !path.includes("redirect");
      return {
        system: "portal",
        ...location,
        logged_in: login ? false : location.origin === "https://studentportal.hku.hk" ? true : null,
        page_kind: login ? "portal_login" : location.origin === "https://studentportal.hku.hk" ? "portal_home" : "portal_redirect"
      };
    }
    if (location.origin === "https://sis-main.hku.hk") {
      const login = path.includes("login") || path.endsWith("z_signon.jsp");
      return {
        system: "sis",
        ...location,
        logged_in: login ? false : null,
        page_kind: login ? "login" : "sis_page"
      };
    }
    if (location.origin === "https://moodle.hku.hk") {
      const login = path.startsWith("/login/");
      const dashboard = path === "/my" || path.startsWith("/my/");
      const course = path.startsWith("/course/");
      return {
        system: "moodle",
        ...location,
        logged_in: login ? false : dashboard || course ? true : null,
        page_kind: login ? "login" : dashboard ? "dashboard" : course ? "course" : "home"
      };
    }
    if (location.origin === "https://julac-hku.primo.exlibrisgroup.com") {
      const account = path.startsWith("/discovery/account");
      const favorites = path.startsWith("/discovery/favorites");
      const search = path.startsWith("/discovery/search");
      return {
        system: "library",
        ...location,
        logged_in: account || favorites ? true : null,
        page_kind: account ? "account" : favorites ? "favorites" : search ? "catalog" : "library_page"
      };
    }
    if (location.origin === "https://lib.hku.hk") {
      return {
        system: "library",
        ...location,
        logged_in: null,
        page_kind: path.startsWith("/hkulauth/") ? "authentication_pending" : "library_page"
      };
    }
    return null;
  }

  function parserVersion(snapshot) {
    return snapshot?.diagnostics?.parser_version ||
      snapshot?.navigation_diagnostics?.parser_version || null;
  }

  function targetFromTab(tab, boundTabId = null, boundSnapshot = null) {
    const target = classifyUrl(tab?.url);
    if (!target) return null;
    const isBound = tab.id === boundTabId && boundSnapshot?.origin === target.origin;
    if (isBound) {
      target.logged_in = boundSnapshot.logged_in ?? target.logged_in;
      target.page_kind = boundSnapshot.page_kind || target.page_kind;
      target.parser_version = parserVersion(boundSnapshot);
    } else {
      target.parser_version = null;
    }
    target.active = Boolean(tab.active);
    target.safe_for_writes = false;
    return target;
  }

  function score(tab, target) {
    return Number(target.logged_in === true) * 1e15 +
      Number(tab.active) * 1e14 + Number(tab.lastAccessed || 0);
  }

  function buildRegistry(tabs, boundTabId = null, boundSnapshot = null) {
    const selected = new Map();
    for (const tab of tabs || []) {
      const target = targetFromTab(tab, boundTabId, boundSnapshot);
      if (!target) continue;
      const candidate = { target, score: score(tab, target) };
      const previous = selected.get(target.system);
      if (!previous || candidate.score > previous.score) selected.set(target.system, candidate);
    }
    return SYSTEM_ORDER
      .filter((system) => selected.has(system))
      .map((system) => selected.get(system).target);
  }

  const api = {
    buildRegistry,
    classifyUrl,
    sanitizedLocation,
    systemOrder: () => [...SYSTEM_ORDER],
    targetPatterns: () => [...TARGET_PATTERNS]
  };
  root.HKUBrowserTargets = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof self !== "undefined" ? self : this);
