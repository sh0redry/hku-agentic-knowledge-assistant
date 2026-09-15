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

  function courseCandidateNodes(documentObject) {
    const nodes = [];
    const seen = new Set();
    for (const selector of [
      "[data-course-id]",
      "a[href*='/course/view.php']",
      "a[href*='course/view.php']"
    ]) {
      let matches = [];
      try {
        matches = documentObject.querySelectorAll(selector);
      } catch (_error) {
        matches = [];
      }
      for (const node of matches) {
        const canonical = node?.closest?.("[data-course-id]") || node;
        if (isCoursePlaceholder(canonical)) continue;
        if (!seen.has(canonical)) {
          seen.add(canonical);
          nodes.push(canonical);
        }
      }
    }
    return nodes;
  }

  function isCoursePlaceholder(node) {
    if (!node) return true;
    try {
      if (node.closest?.("template")) return true;
    } catch (_error) {
      // Continue with the attribute/link checks.
    }
    const rawId = normalizeText(
      node?.dataset?.courseId ||
      node?.dataset?.courseid ||
      node?.getAttribute?.("data-course-id") ||
      node?.getAttribute?.("data-courseid")
    );
    return !rawId && !courseAnchor(node);
  }

  function coursePlaceholderCount(documentObject) {
    let matches = [];
    try {
      matches = documentObject.querySelectorAll("[data-course-id]");
    } catch (_error) {
      return 0;
    }
    return [...matches].filter(isCoursePlaceholder).length;
  }

  function courseAnchor(node) {
    const href = node?.getAttribute?.("href");
    if (href && /course\/view\.php/i.test(href)) return node;
    try {
      return node?.querySelector?.("a[href*='course/view.php'], a[href*='/course/view.php']") || null;
    } catch (_error) {
      return null;
    }
  }

  function courseId(node, anchor) {
    const containers = [node, node?.closest?.("[data-course-id]")].filter(Boolean);
    for (const container of containers) {
      const rawValues = [
        container?.dataset?.courseId,
        container?.dataset?.courseid,
        container?.getAttribute?.("data-course-id"),
        container?.getAttribute?.("data-courseid")
      ];
      for (const rawValue of rawValues) {
        const value = normalizeText(rawValue);
        if (/^\d{1,20}$/.test(value)) return value;
        const prefixed = value.match(/^course[-_:]?(\d{1,20})$/i);
        if (prefixed) return prefixed[1];
      }
    }
    try {
      const url = new URL(anchor?.getAttribute?.("href") || "", MOODLE_ORIGIN);
      const value = url.searchParams.get("id") ||
        url.searchParams.get("courseid") ||
        url.searchParams.get("course_id") || "";
      return url.origin === MOODLE_ORIGIN && url.pathname.toLowerCase() === "/course/view.php" && /^\d{1,20}$/.test(value)
        ? value
        : null;
    } catch (_error) {
      return null;
    }
  }

  function courseContainer(node) {
    return node?.closest?.(
      "[data-course-id], [data-region='course-content'], .dashboard-card, .coursebox, .course-info-container"
    ) || node;
  }

  function courseName(container, anchor) {
    function meaningfulName(value) {
      let name = normalizeText(value);
      name = name.replace(/^course\s+name\s*[:\-]?\s*/i, "");
      if (!name || /^(?:course name|view course|course image)$/i.test(name)) return null;
      if (/\bcourse is (?:not )?starred\b/i.test(name)) return null;
      if (/^(?:actions?|more actions?)\s+(?:for|on)\b/i.test(name)) return null;
      return name.slice(0, 300);
    }

    for (const selector of [
      "[data-region='course-name']",
      ".coursename",
      "a.coursename",
      ".dashboard-card-title",
      "[data-course-name]",
      ".card-title",
      ".multiline",
      "a.aalink",
      "h3",
      "h4"
    ]) {
      try {
        const node = container?.querySelector?.(selector);
        const candidate = meaningfulName(
          node?.textContent ||
          node?.getAttribute?.("aria-label") ||
          node?.getAttribute?.("title") ||
          node?.getAttribute?.("data-course-name")
        );
        if (candidate) return candidate;
      } catch (_error) {
        // Try the next explicit title shape.
      }
    }

    for (const value of [
      container?.dataset?.courseName,
      container?.getAttribute?.("data-course-name"),
      anchor?.textContent,
      anchor?.getAttribute?.("aria-label"),
      anchor?.getAttribute?.("title"),
      anchor?.querySelector?.("img[alt]")?.getAttribute?.("alt")
    ]) {
      const candidate = meaningfulName(value);
      if (candidate) return candidate;
    }
    return "";
  }

  function courseState(container) {
    const explicit = normalizeText(
      container?.dataset?.courseState || container?.getAttribute?.("data-course-state")
    ).toLowerCase();
    const className = normalizeText(container?.className).toLowerCase();
    const sample = `${explicit} ${className} ${normalizeText(container?.textContent).toLowerCase().slice(0, 500)}`;
    if (/\b(?:past|archived|completed)\b/.test(sample)) return "past";
    if (/\b(?:future|upcoming)\b/.test(sample)) return "future";
    if (/\b(?:current|in progress|active)\b/.test(sample)) return "current";
    return "unknown";
  }

  function courseIdentity(name) {
    const upper = String(name || "").toUpperCase();
    const codeMatch = upper.match(/\b([A-Z]{2,8})\s*([0-9]{4}[A-Z]?)\b/);
    const courseCode = codeMatch ? `${codeMatch[1]}${codeMatch[2]}` : null;
    const yearMatch = upper.match(/\b(20\d{2})\s*[-/]\s*(\d{2}|20\d{2})\b/);
    const academicYear = yearMatch
      ? `${yearMatch[1]}-${yearMatch[2].slice(-2)}`
      : null;
    let section = null;
    const labelledSection = upper.match(/\b(?:SECTION|SECT|SEC)\s*[:#-]?\s*([0-9]{1,3}[A-Z]{0,2})\b/);
    if (labelledSection) {
      section = labelledSection[1];
    } else if (codeMatch) {
      const suffix = upper.slice((codeMatch.index || 0) + codeMatch[0].length);
      const suffixSection = suffix.match(/^\s*[-_/]\s*([0-9]{1,3}[A-Z]{1,2})\b/);
      if (suffixSection) section = suffixSection[1];
    }
    return { course_code: courseCode, section, academic_year: academicYear };
  }

  function parseCourses(documentObject, locationObject) {
    const dashboard = inspect(documentObject, locationObject);
    if (dashboard.logged_in !== true || dashboard.page_kind !== "dashboard") {
      const error = new Error("Open the authenticated Moodle Dashboard before listing courses.");
      error.code = dashboard.logged_in === false
        ? "MOODLE_LOGIN_REQUIRED"
        : "MOODLE_DASHBOARD_NOT_READY";
      throw error;
    }
    const candidates = courseCandidateNodes(documentObject);
    const courses = [];
    const coursesById = new Map();
    let unparsed = 0;
    let missingId = 0;
    let missingName = 0;
    let duplicates = 0;
    for (const node of candidates) {
      const anchor = courseAnchor(node);
      const id = courseId(node, anchor);
      const container = courseContainer(node);
      const name = courseName(container, anchor);
      if (!id) {
        unparsed += 1;
        missingId += 1;
        if (!name) missingName += 1;
        continue;
      }
      const existing = coursesById.get(id);
      if (existing) {
        duplicates += 1;
        if (!existing.name && name) existing.name = name;
        const state = courseState(container);
        if (existing.state === "unknown" && state !== "unknown") existing.state = state;
        continue;
      }
      coursesById.set(id, {
        course_id: id,
        name,
        state: courseState(container)
      });
    }
    for (const course of coursesById.values()) {
      if (!course.name) {
        unparsed += 1;
        missingName += 1;
        continue;
      }
      courses.push({
        course_id: course.course_id,
        ...courseIdentity(course.name),
        name: course.name,
        state: course.state
      });
    }
    return {
      ...dashboard,
      course_count: courses.length,
      courses,
      diagnostics: {
        ...dashboard.diagnostics,
        course_candidate_count: candidates.length,
        parsed_course_count: courses.length,
        unparsed_course_candidate_count: unparsed,
        missing_course_id_candidate_count: missingId,
        missing_course_name_candidate_count: missingName,
        duplicate_course_candidate_count: duplicates,
        course_placeholder_candidate_count: coursePlaceholderCount(documentObject)
      }
    };
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
        parser_version: "0.2.4",
        dashboard_marker_found: dashboardMarker,
        login_marker_found: loginMarker,
        user_menu_found: userMenuMarker,
        course_link_candidate_count: courseCandidateNodes(documentObject).length,
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

  const api = { inspect, normalizeText, openDashboard, parseCourses, courseIdentity };
  root.HKUMoodleParser = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof self !== "undefined" ? self : this);
