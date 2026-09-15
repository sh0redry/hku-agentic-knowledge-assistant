(function (root) {
  "use strict";

  const MOODLE_ORIGIN = "https://moodle.hku.hk";

  function normalizeText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function pathOf(locationObject) {
    return String(locationObject?.pathname || "/").toLowerCase();
  }

  function markerCount(documentObject, selector) {
    try {
      return documentObject.querySelectorAll(selector).length;
    } catch (_error) {
      return 0;
    }
  }

  function inspect(documentObject, locationObject) {
    if (!locationObject || locationObject.origin !== MOODLE_ORIGIN) {
      const error = new Error("The active page is not the allowed HKU Moodle origin.");
      error.code = "WRONG_MOODLE_ORIGIN";
      throw error;
    }
    const path = pathOf(locationObject);
    const text = normalizeText(documentObject.body?.textContent);
    const lower = text.toLowerCase();
    const hasPassword = Boolean(documentObject.querySelector("input[type='password']"));
    const loginMarker = path.startsWith("/login/") || hasPassword ||
      /log in to the site|hku portal user login|guest access/.test(lower.slice(0, 4000));
    const blockedMarker = /access denied|not authorized|session (?:has )?expired/.test(lower);
    const userMenuMarker = Boolean(documentObject.querySelector(
      ".usermenu, [data-region='user-menu'], [aria-label*='User menu' i], a[href*='/login/logout.php']"
    ));
    const dashboardPath = path === "/my" || path.startsWith("/my/");
    const dashboardTextMarker = /\bdashboard\b/.test(lower) &&
      /course overview|timeline|upcoming events|my courses/.test(lower);
    const dashboardMarker = dashboardPath && (dashboardTextMarker || userMenuMarker);
    const coursePageMarker = path.startsWith("/course/") && userMenuMarker;
    const homeMarker = !loginMarker && userMenuMarker;
    const pageKind = loginMarker
      ? "login"
      : blockedMarker
        ? "blocked"
        : dashboardMarker
          ? "dashboard"
          : coursePageMarker
            ? "course"
            : homeMarker
              ? "home"
              : "unknown";
    const authenticated = ["dashboard", "course", "home"].includes(pageKind);
    return {
      bound: true,
      origin: MOODLE_ORIGIN,
      logged_in: loginMarker || blockedMarker ? false : authenticated ? true : null,
      page_kind: pageKind,
      term_label: null,
      course_count: 0,
      temporary_course_count: 0,
      schedule_course_count: 0,
      available_terms: [],
      diagnostics: {
        parser_version: "0.1.0",
        dashboard_marker_found: dashboardMarker,
        login_marker_found: loginMarker,
        user_menu_found: userMenuMarker,
        course_link_candidate_count: markerCount(documentObject, "a[href*='/course/view.php']"),
        timeline_marker_found: /\btimeline\b/.test(lower),
        upcoming_marker_found: /upcoming events|upcoming/.test(lower),
        todo_marker_found: /to-do|todo|action events/.test(lower)
      }
    };
  }

  function openDashboard(documentObject, locationObject) {
    const snapshot = inspect(documentObject, locationObject);
    if (snapshot.logged_in !== true) {
      const error = new Error("Complete the HKU Portal User login and any MFA in Moodle.");
      error.code = "MOODLE_LOGIN_REQUIRED";
      throw error;
    }
    if (snapshot.page_kind === "dashboard") {
      return { navigation_started: false, snapshot };
    }
    if (!["home", "course"].includes(snapshot.page_kind)) {
      const error = new Error(`Cannot open Dashboard from Moodle page kind '${snapshot.page_kind}'.`);
      error.code = "MOODLE_DASHBOARD_NOT_READY";
      throw error;
    }
    locationObject.assign(`${MOODLE_ORIGIN}/my/`);
    return { navigation_started: true, snapshot };
  }

  const api = { inspect, normalizeText, openDashboard };
  root.HKUMoodleParser = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof self !== "undefined" ? self : this);
