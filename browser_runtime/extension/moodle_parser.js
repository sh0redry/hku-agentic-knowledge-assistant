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

  function activityCandidateNodes(documentObject) {
    function collect(selectors) {
      const nodes = [];
      const seen = new Set();
      for (const selector of selectors) {
        let matches = [];
        try {
          matches = documentObject.querySelectorAll(selector);
        } catch (_error) {
          matches = [];
        }
        for (const node of matches) {
          if (!seen.has(node)) {
            seen.add(node);
            nodes.push(node);
          }
        }
      }
      return nodes;
    }
    const candidates = collect([
      "[data-region='event-list-item']",
      "[data-event-id][data-event-timestart]",
      "[data-event-id][data-event-timesort]",
      "[data-event-name][data-event-timestart]",
      ".block_timeline .event[data-timestamp]",
      ".block_calendar_upcoming .event[data-timestamp]"
    ]);
    const seen = new Set(candidates);
    for (const anchor of collect(["a[href*='/mod/']", "a[href*='mod/']"])) {
      let candidate = anchor;
      let current = anchor;
      for (let depth = 0; depth < 5 && current; depth += 1) {
        const text = normalizeText(current.textContent);
        const hasDate = /\b20\d{2}\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[A-Za-z]*\b|\b(?:Today|Tomorrow)\b|\b\d{1,2}[/-]\d{1,2}[/-](?:20)?\d{2}\b/i.test(text);
        const hasTime = /\b\d{1,2}:\d{2}\s*(?:AM|PM)?\b/i.test(text);
        if (hasDate && hasTime && text.length <= 1500 && parseMoodleDisplayDate(text)) {
          candidate = current;
          break;
        }
        current = current.parentElement || null;
      }
      const text = normalizeText(candidate?.textContent);
      if (
        text.length <= 1500 &&
        /\b20\d{2}\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[A-Za-z]*\b|\b(?:Today|Tomorrow)\b|\b\d{1,2}[/-]\d{1,2}[/-](?:20)?\d{2}\b/i.test(text) &&
        /\b\d{1,2}:\d{2}\s*(?:AM|PM)?\b/i.test(text) &&
        Boolean(parseMoodleDisplayDate(text)) &&
        !seen.has(candidate)
      ) {
        seen.add(candidate);
        candidates.push(candidate);
      }
    }
    return candidates;
  }

  function activityValue(node, names) {
    for (const name of names) {
      const datasetName = name.replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase());
      const value = normalizeText(
        node?.dataset?.[datasetName] || node?.getAttribute?.(`data-${name}`)
      );
      if (value) return value;
    }
    return "";
  }

  function scopedActivityValue(node, names) {
    const direct = activityValue(node, names);
    if (direct) return direct;
    for (const name of names) {
      try {
        const descendant = node?.querySelector?.(`[data-${name}]`);
        const value = activityValue(descendant, [name]);
        if (value) return value;
      } catch (_error) {
        // Try the next explicit nested data attribute.
      }
    }
    return "";
  }

  function meaningfulActivityText(value) {
    const text = normalizeText(value);
    if (!text || /^(?:view|open|more|actions?|activity)$/i.test(text)) return "";
    return text.slice(0, 300);
  }

  function activityAnchor(node) {
    try {
      const href = node?.getAttribute?.("href") || "";
      if (/\/?mod\//i.test(href)) return node;
    } catch (_error) {
      // Continue with a descendant activity link.
    }
    try {
      return node?.querySelector?.("a[href*='/mod/'], a[href*='mod/']") || null;
    } catch (_error) {
      return null;
    }
  }

  function activityTitle(node, anchor) {
    for (const selector of [
      "[data-region='event-name'] a",
      "h6.event-name a",
      ".event-name a",
      ".event-name-container a",
      "[data-region='event-name']",
      ".event-name",
      ".event-name-container",
      "[data-event-name]",
      "h6",
      "h5"
    ]) {
      try {
        const candidateNode = node?.querySelector?.(selector);
        const candidate = meaningfulActivityText(
          candidateNode?.textContent ||
          candidateNode?.getAttribute?.("data-event-name") ||
          candidateNode?.getAttribute?.("aria-label") ||
          candidateNode?.getAttribute?.("title")
        );
        if (candidate) return candidate;
      } catch (_error) {
        // Try the next explicit activity title shape.
      }
    }
    for (const value of [
      scopedActivityValue(node, ["event-name", "activity-name"]),
      anchor?.textContent,
      anchor?.getAttribute?.("aria-label"),
      anchor?.getAttribute?.("title")
    ]) {
      const candidate = meaningfulActivityText(value);
      if (candidate) return candidate;
    }
    return "";
  }

  function numericId(value) {
    const normalized = normalizeText(value);
    return /^\d{1,20}$/.test(normalized) ? normalized : null;
  }

  function idFromUrl(anchorOrUrl, parameter = "id") {
    try {
      const rawUrl = typeof anchorOrUrl === "string"
        ? anchorOrUrl
        : anchorOrUrl?.getAttribute?.("href") || "";
      const url = new URL(rawUrl, MOODLE_ORIGIN);
      const value = url.searchParams.get(parameter) || "";
      return url.origin === MOODLE_ORIGIN ? numericId(value) : null;
    } catch (_error) {
      return null;
    }
  }

  function machineDate(value) {
    const normalized = normalizeText(value);
    if (!normalized) return null;
    if (/^\d{9,13}$/.test(normalized)) {
      const number = Number(normalized);
      const milliseconds = normalized.length >= 12 ? number : number * 1000;
      const date = new Date(milliseconds);
      return Number.isFinite(date.getTime()) && date.getUTCFullYear() >= 2000 && date.getUTCFullYear() <= 2100
        ? date.toISOString()
        : null;
    }
    if (!/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:?\d{2})$/i.test(normalized)) return null;
    const date = new Date(normalized);
    return Number.isFinite(date.getTime()) ? date.toISOString() : null;
  }

  function activityMachineDueAt(node) {
    const explicit = scopedActivityValue(node, [
      "event-time-sort", "event-timesort", "event-timestart", "event-timestamp",
      "time-sort", "timestart", "timestamp", "due-date", "due-time", "end-time"
    ]);
    const explicitDate = machineDate(explicit);
    if (explicitDate) return explicitDate;
    for (const selector of ["time[datetime]", "[data-timestamp]"]) {
      try {
        const dateNode = node?.querySelector?.(selector);
        const value = dateNode?.getAttribute?.("datetime") ||
          dateNode?.getAttribute?.("data-timestamp");
        const parsed = machineDate(value);
        if (parsed) return parsed;
      } catch (_error) {
        // Require another explicit machine-readable deadline.
      }
    }
    return null;
  }

  function hongKongDateParts(date = new Date()) {
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Hong_Kong",
      year: "numeric",
      month: "numeric",
      day: "numeric"
    }).formatToParts(date);
    const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
    return { year: Number(values.year), month: Number(values.month), day: Number(values.day) };
  }

  function hongKongIso(year, month, day, hour, minute) {
    const calendarDate = new Date(Date.UTC(year, month - 1, day));
    if (
      calendarDate.getUTCFullYear() !== year ||
      calendarDate.getUTCMonth() !== month - 1 ||
      calendarDate.getUTCDate() !== day ||
      hour < 0 || hour > 23 || minute < 0 || minute > 59
    ) return null;
    return new Date(Date.UTC(year, month - 1, day, hour, minute) - 8 * 60 * 60 * 1000)
      .toISOString();
  }

  function clockParts(hourText, minuteText, meridiem) {
    let hour = Number(hourText);
    const minute = Number(minuteText);
    if (meridiem) {
      if (hour < 1 || hour > 12) return null;
      if (meridiem.toLowerCase() === "pm" && hour !== 12) hour += 12;
      if (meridiem.toLowerCase() === "am" && hour === 12) hour = 0;
    }
    return hour >= 0 && hour <= 23 && minute >= 0 && minute <= 59
      ? { hour, minute }
      : null;
  }

  function parseMoodleDisplayDate(value, now = new Date()) {
    const text = normalizeText(value).replace(/\u00a0/g, " ");
    const clockPattern = "(\\d{1,2}):(\\d{2})\\s*(AM|PM)?";
    const relative = text.match(new RegExp(`\\b(Today|Tomorrow)\\b[^0-9]{0,20}${clockPattern}`, "i"));
    if (relative) {
      const clock = clockParts(relative[2], relative[3], relative[4]);
      if (!clock) return null;
      const current = hongKongDateParts(now);
      const base = new Date(Date.UTC(current.year, current.month - 1, current.day));
      if (relative[1].toLowerCase() === "tomorrow") base.setUTCDate(base.getUTCDate() + 1);
      return hongKongIso(
        base.getUTCFullYear(), base.getUTCMonth() + 1, base.getUTCDate(),
        clock.hour, clock.minute
      );
    }
    const months = {
      jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6,
      jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12
    };
    const dayFirst = text.match(new RegExp(
      `(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)?[,]?\\s*` +
      `(\\d{1,2})\\s+([A-Za-z]{3,9})\\s+(20\\d{2})[,]?\\s*(?:at\\s+)?${clockPattern}`,
      "i"
    ));
    const monthFirst = text.match(new RegExp(
      `(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)?[,]?\\s*` +
      `([A-Za-z]{3,9})\\s+(\\d{1,2})[,]?\\s+(20\\d{2})[,]?\\s*(?:at\\s+)?${clockPattern}`,
      "i"
    ));
    const match = dayFirst || monthFirst;
    if (match) {
      const monthToken = (dayFirst ? match[2] : match[1]).slice(0, 3).toLowerCase();
      const month = months[monthToken];
      const day = Number(dayFirst ? match[1] : match[2]);
      const clock = clockParts(match[4], match[5], match[6]);
      return month && clock
        ? hongKongIso(Number(match[3]), month, day, clock.hour, clock.minute)
        : null;
    }
    const numeric = text.match(new RegExp(
      `\\b(\\d{1,2})[/-](\\d{1,2})[/-](20\\d{2})\\b[^0-9]{0,20}${clockPattern}`,
      "i"
    ));
    if (numeric) {
      const clock = clockParts(numeric[4], numeric[5], numeric[6]);
      return clock
        ? hongKongIso(Number(numeric[3]), Number(numeric[2]), Number(numeric[1]), clock.hour, clock.minute)
        : null;
    }
    const dayFirstNoYear = text.match(new RegExp(
      `(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)?[,]?\\s*` +
      `(\\d{1,2})\\s+([A-Za-z]{3,9})[,]?\\s*(?:at\\s+)?${clockPattern}`,
      "i"
    ));
    const monthFirstNoYear = text.match(new RegExp(
      `(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)?[,]?\\s*` +
      `([A-Za-z]{3,9})\\s+(\\d{1,2})[,]?\\s*(?:at\\s+)?${clockPattern}`,
      "i"
    ));
    const noYear = dayFirstNoYear || monthFirstNoYear;
    if (!noYear) return null;
    const monthToken = (dayFirstNoYear ? noYear[2] : noYear[1]).slice(0, 3).toLowerCase();
    const month = months[monthToken];
    const day = Number(dayFirstNoYear ? noYear[1] : noYear[2]);
    const clock = clockParts(noYear[3], noYear[4], noYear[5]);
    if (!month || !clock) return null;
    const current = hongKongDateParts(now);
    let year = current.year;
    let result = hongKongIso(year, month, day, clock.hour, clock.minute);
    if (!result) return null;
    if (new Date(result).getTime() < now.getTime() - 48 * 60 * 60 * 1000) {
      year += 1;
      result = hongKongIso(year, month, day, clock.hour, clock.minute);
    }
    return result;
  }

  function activityVisibleDueTexts(node) {
    const values = [];
    for (const selector of [
      "[data-region='event-time']",
      "[data-region='event-date']",
      ".event-time",
      ".event-date",
      "time",
      ".date",
      ".text-right small"
    ]) {
      try {
        const dateNode = node?.querySelector?.(selector);
        for (const value of [
          dateNode?.textContent,
          dateNode?.getAttribute?.("aria-label"),
          dateNode?.getAttribute?.("title")
        ]) {
          const normalized = normalizeText(value);
          if (normalized && !values.includes(normalized)) values.push(normalized);
        }
      } catch (_error) {
        // Continue with the next explicit visible date shape.
      }
    }
    const rowText = normalizeText(node?.textContent);
    if (rowText && !values.includes(rowText)) values.push(rowText);
    try {
      const group = node?.closest?.(
        "[data-region='event-list-group-container'], [data-region='event-list-group'], .event-list-group"
      );
      const groupDate = normalizeText(
        group?.querySelector?.("[data-region='event-list-group-date'], h4, h5")?.textContent
      );
      if (groupDate) {
        for (const itemText of [...values]) {
          const combined = normalizeText(`${groupDate} ${itemText}`);
          if (combined && !values.includes(combined)) values.push(combined);
        }
      }
    } catch (_error) {
      // The complete row text remains available as a conservative fallback.
    }
    return values;
  }

  function displayDateHasExplicitYear(value) {
    return /\b20\d{2}\b/.test(normalizeText(value));
  }

  function activityDue(node) {
    const machine = activityMachineDueAt(node);
    if (machine) return { due_at: machine, due_at_source: "machine", combined_fragments: false };
    const values = activityVisibleDueTexts(node);
    for (const value of values) {
      const parsed = parseMoodleDisplayDate(value);
      if (parsed) {
        return {
          due_at: parsed,
          due_at_source: displayDateHasExplicitYear(value)
            ? "display_text_hong_kong"
            : "display_text_hong_kong_inferred_year",
          combined_fragments: false
        };
      }
    }
    const dateFragments = values.filter((value) =>
      /\b20\d{2}\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[A-Za-z]*\b|\b(?:Today|Tomorrow)\b|\b\d{1,2}[/-]\d{1,2}[/-](?:20)?\d{2}\b/i.test(value)
    );
    const timeFragments = values.filter((value) =>
      /\b\d{1,2}:\d{2}\s*(?:AM|PM)?\b/i.test(value)
    );
    for (const dateValue of dateFragments) {
      for (const timeValue of timeFragments) {
        if (dateValue === timeValue) continue;
        const combined = normalizeText(`${dateValue} ${timeValue}`);
        const parsed = parseMoodleDisplayDate(combined);
        if (parsed) {
          return {
            due_at: parsed,
            due_at_source: displayDateHasExplicitYear(dateValue)
              ? "display_text_hong_kong_combined_fragments"
              : "display_text_hong_kong_combined_fragments_inferred_year",
            combined_fragments: true
          };
        }
      }
    }
    return { due_at: null, due_at_source: null, combined_fragments: false };
  }

  function activityCourse(node) {
    let courseAnchor = null;
    try {
      courseAnchor = node?.querySelector?.("a[href*='/course/view.php'], a[href*='course/view.php']") || null;
    } catch (_error) {
      courseAnchor = null;
    }
    let name = "";
    for (const selector of ["[data-region='course-name']", ".course-name", ".event-course"]) {
      try {
        const candidate = meaningfulActivityText(node?.querySelector?.(selector)?.textContent);
        if (candidate) {
          name = candidate;
          break;
        }
      } catch (_error) {
        // Continue with the next course label shape.
      }
    }
    if (!name) name = meaningfulActivityText(courseAnchor?.textContent);
    if (!name) {
      name = meaningfulActivityText(
        scopedActivityValue(node, ["event-course-name", "event-coursename", "course-name"])
      );
    }
    return {
      course_id: numericId(scopedActivityValue(node, [
        "event-course-id", "event-courseid", "course-id", "courseid"
      ])) || idFromUrl(courseAnchor),
      course_name: name || null
    };
  }

  function activityUrl(node, anchor) {
    const rawUrl = normalizeText(
      anchor?.getAttribute?.("href") || scopedActivityValue(node, ["event-url", "activity-url"])
    );
    if (!rawUrl) return "";
    try {
      const url = new URL(rawUrl, MOODLE_ORIGIN);
      return url.origin === MOODLE_ORIGIN && url.pathname.toLowerCase().startsWith("/mod/")
        ? url.href
        : "";
    } catch (_error) {
      return "";
    }
  }

  function activityType(node, anchor) {
    const explicit = scopedActivityValue(node, [
      "event-component", "event-module-name", "event-modulename",
      "activity-type", "module-name", "modulename", "event-type"
    ]).toLowerCase().replace(/[_-]+/g, " ");
    let path = "";
    try {
      path = new URL(activityUrl(node, anchor), MOODLE_ORIGIN).pathname.toLowerCase();
    } catch (_error) {
      path = "";
    }
    const sample = `${explicit} ${path}`;
    if (/\bassign(?:ment)?\b|\/mod\/assign\//.test(sample)) return "assignment";
    if (/\bquiz\b|\/mod\/quiz\//.test(sample)) return "quiz";
    if (/\bworkshop\b|\/mod\/workshop\//.test(sample)) return "workshop";
    if (/\blesson\b|\/mod\/lesson\//.test(sample)) return "lesson";
    if (/\bforum\b|\/mod\/forum\//.test(sample)) return "forum";
    return "other";
  }

  function isActivityPlaceholder(node) {
    const text = normalizeText(node?.textContent).toLowerCase();
    return /no upcoming activities|nothing due|no events/.test(text);
  }

  function activitySource(node) {
    try {
      if (node?.closest?.(".block_calendar_upcoming")) return "upcoming";
      if (node?.closest?.(
        "[data-region='todo'], [data-region='to-do'], [data-block='todo'], .block_todo, .todo-item"
      )) return "todo";
    } catch (_error) {
      // Fall through to structural classification.
    }
    const hasStandardEventShape = Boolean(
      scopedActivityValue(node, ["event-id", "eventid", "event-timestart", "event-timesort"])
    );
    return hasStandardEventShape ? "timeline" : "todo";
  }

  function parseUpcomingAssignments(documentObject, locationObject) {
    const dashboard = inspect(documentObject, locationObject);
    if (dashboard.logged_in !== true || dashboard.page_kind !== "dashboard") {
      const error = new Error("Open the authenticated Moodle Dashboard before reading upcoming assignments.");
      error.code = dashboard.logged_in === false
        ? "MOODLE_LOGIN_REQUIRED"
        : "MOODLE_DASHBOARD_NOT_READY";
      throw error;
    }
    const rawCandidates = activityCandidateNodes(documentObject);
    const candidates = rawCandidates.filter((node) => !isActivityPlaceholder(node));
    const assignments = [];
    const seen = new Set();
    let unparsed = 0;
    let missingTitle = 0;
    let missingDueAt = 0;
    let duplicates = 0;
    let displayDatesParsed = 0;
    let inferredYears = 0;
    let combinedDateFragmentsParsed = 0;
    let visibleDateTextCandidates = 0;
    let dateTextsWithYear = 0;
    let dateTextsWithMonth = 0;
    let dateTextsWith12HourTime = 0;
    let dateTextsWith24HourTime = 0;
    let dateTextsWithRelativeDay = 0;
    let dateTextsWithNumericDate = 0;
    for (const node of candidates) {
      const anchor = activityAnchor(node);
      const title = activityTitle(node, anchor);
      const visibleDueTexts = activityVisibleDueTexts(node);
      if (visibleDueTexts.length) visibleDateTextCandidates += 1;
      const dateSample = visibleDueTexts.join(" ");
      if (/\b20\d{2}\b/.test(dateSample)) dateTextsWithYear += 1;
      if (/\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[A-Za-z]*\b/i.test(dateSample)) dateTextsWithMonth += 1;
      if (/\b\d{1,2}:\d{2}\s*(?:AM|PM)\b/i.test(dateSample)) dateTextsWith12HourTime += 1;
      if (/\b(?:[01]?\d|2[0-3]):[0-5]\d\b/.test(dateSample)) dateTextsWith24HourTime += 1;
      if (/\b(?:Today|Tomorrow)\b/i.test(dateSample)) dateTextsWithRelativeDay += 1;
      if (/\b\d{1,2}[/-]\d{1,2}[/-](?:20)?\d{2}\b/.test(dateSample)) dateTextsWithNumericDate += 1;
      const due = activityDue(node);
      const dueAt = due.due_at;
      if (!title || !dueAt) {
        unparsed += 1;
        if (!title) missingTitle += 1;
        if (!dueAt) missingDueAt += 1;
        continue;
      }
      if (due.due_at_source?.startsWith("display_text_hong_kong")) displayDatesParsed += 1;
      if (due.due_at_source?.includes("inferred_year")) inferredYears += 1;
      if (due.combined_fragments) combinedDateFragmentsParsed += 1;
      const course = activityCourse(node);
      const eventId = numericId(scopedActivityValue(node, ["event-id", "eventid"]));
      const moduleId = numericId(scopedActivityValue(node, [
        "event-instance", "event-instance-id", "module-id", "instance-id"
      ])) || idFromUrl(activityUrl(node, anchor));
      const key = eventId
        ? `event:${eventId}`
        : moduleId
          ? `module:${moduleId}|${dueAt}`
          : `text:${course.course_id || "none"}|${dueAt}|${title}`;
      if (seen.has(key)) {
        duplicates += 1;
        continue;
      }
      seen.add(key);
      assignments.push({
        event_id: eventId,
        module_id: moduleId,
        ...course,
        title,
        activity_type: activityType(node, anchor),
        due_at: dueAt,
        due_at_source: due.due_at_source,
        source: activitySource(node)
      });
    }
    assignments.sort((left, right) => left.due_at.localeCompare(right.due_at));
    return {
      ...dashboard,
      assignment_count: assignments.length,
      assignments,
      diagnostics: {
        ...dashboard.diagnostics,
        assignment_candidate_count: candidates.length,
        parsed_assignment_count: assignments.length,
        unparsed_assignment_candidate_count: unparsed,
        missing_assignment_title_candidate_count: missingTitle,
        missing_assignment_due_at_candidate_count: missingDueAt,
        duplicate_assignment_candidate_count: duplicates,
        assignment_placeholder_candidate_count: rawCandidates.length - candidates.length,
        visible_assignment_date_text_candidate_count: visibleDateTextCandidates,
        parsed_assignment_display_date_count: displayDatesParsed,
        inferred_assignment_year_count: inferredYears,
        combined_assignment_date_fragments_parsed_count: combinedDateFragmentsParsed,
        assignment_date_text_with_year_count: dateTextsWithYear,
        assignment_date_text_with_month_name_count: dateTextsWithMonth,
        assignment_date_text_with_12_hour_time_count: dateTextsWith12HourTime,
        assignment_date_text_with_24_hour_time_count: dateTextsWith24HourTime,
        assignment_date_text_with_relative_day_count: dateTextsWithRelativeDay,
        assignment_date_text_with_numeric_date_count: dateTextsWithNumericDate
      }
    };
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
        parser_version: "0.3.5",
        dashboard_marker_found: dashboardMarker,
        login_marker_found: loginMarker,
        user_menu_found: userMenuMarker,
        course_link_candidate_count: courseCandidateNodes(documentObject).length,
        timeline_marker_found: /\btimeline\b/.test(lower),
        upcoming_marker_found: /upcoming events|upcoming/.test(lower),
        todo_marker_found: /\bto\s*-?\s*do\b|\btodo\b|action events/.test(lower)
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

  const api = {
    inspect,
    normalizeText,
    openDashboard,
    parseCourses,
    parseUpcomingAssignments,
    parseMoodleDisplayDate,
    courseIdentity
  };
  root.HKUMoodleParser = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof self !== "undefined" ? self : this);
