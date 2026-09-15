(function (root) {
  "use strict";

  const SIS_ORIGIN = "https://sis-main.hku.hk";
  const COURSE_PATTERN = /\b([A-Z]{2,8})\s*([0-9]{3,5}[A-Z]?)\b/i;
  const COURSE_SECTION_PATTERN =
    /\b([A-Z]{2,8})\s*([0-9]{3,5}[A-Z]?)\s*[-\u2010-\u2015]\s*([A-Z0-9-]{1,20})\b/i;
  const CLASS_PATTERN = /\bclass\s*(?:nbr|number|no\.?|#)\s*:?\s*([0-9]{3,8})\b/i;
  const SECTION_PATTERN = /\bsection\s*:?\s*([A-Z0-9-]{1,20})\b/i;
  const DAY_TIME_PATTERN = /\b(Mo|Tu|We|Th|Fr|Sa|Su)\s+([0-2][0-9]:[0-5][0-9])\s*[-\u2010-\u2015]\s*([0-2][0-9]:[0-5][0-9])\b/gi;
  const WEEKDAYS = {
    Mo: "monday", Tu: "tuesday", We: "wednesday", Th: "thursday",
    Fr: "friday", Sa: "saturday", Su: "sunday"
  };

  function normalizeText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function normalizeHeader(value) {
    return normalizeText(value).toLowerCase().replace(/[^a-z0-9]+/g, " ");
  }

  function textLines(value) {
    return String(value || "")
      .split(/[\r\n]+/)
      .map(normalizeText)
      .filter(Boolean);
  }

  function parseDayTimes(value) {
    const meetings = [];
    for (const match of String(value || "").matchAll(DAY_TIME_PATTERN)) {
      if (match[3] <= match[2]) continue;
      meetings.push({
        weekday: WEEKDAYS[match[1][0].toUpperCase() + match[1].slice(1).toLowerCase()],
        start_time: match[2],
        end_time: match[3]
      });
    }
    return meetings;
  }

  function valueFromColumn(cells, headers, predicate) {
    const index = headers.findIndex(predicate);
    return index >= 0 && index < cells.length ? normalizeText(cells[index]) : "";
  }

  function firstMatch(values, pattern) {
    for (const value of values) {
      const match = normalizeText(value).match(pattern);
      if (match) return match;
    }
    return null;
  }

  function parseCourseRow(cells, headers) {
    const normalizedCells = cells.map(normalizeText);
    const normalizedHeaders = headers.map(normalizeHeader);
    const rowText = normalizeText(normalizedCells.join(" "));
    const courseCell = valueFromColumn(
      normalizedCells,
      normalizedHeaders,
      (header) =>
        header === "class" || header.includes("course") || header.includes("subject")
    );
    // PeopleSoft nests presentation tables. A header collected from an outer
    // table can point at the wrong direct cell, so the full row must remain an
    // independent fallback even when courseCell is non-empty.
    const combinedCourseMatch = firstMatch([courseCell, rowText], COURSE_SECTION_PATTERN);
    const courseMatch = combinedCourseMatch || firstMatch([courseCell, rowText], COURSE_PATTERN);
    if (!courseMatch) return null;

    const sectionCell = valueFromColumn(
      normalizedCells,
      normalizedHeaders,
      (header) => header.includes("section") || header === "sec"
    );
    const explicitSectionMatch = firstMatch([sectionCell, rowText], SECTION_PATTERN);
    const plainSectionMatch = normalizeText(sectionCell).match(/^([A-Z0-9-]{1,20})$/i);
    const section = plainSectionMatch ? plainSectionMatch[1] :
      (combinedCourseMatch
        ? combinedCourseMatch[3]
        : explicitSectionMatch
          ? explicitSectionMatch[1]
          : "");

    const classCell = valueFromColumn(
      normalizedCells,
      normalizedHeaders,
      (header) => header.includes("class") && /nbr|number|no/.test(header)
    );
    const classMatch = firstMatch([classCell, rowText], CLASS_PATTERN);
    const classNumberMatch = normalizeText(classCell).match(/^([0-9]{3,8})$/);
    const parenthesizedClassMatch = firstMatch(
      [courseCell, rowText],
      /\(([0-9]{3,8})\)/
    );
    const classNumber = classNumberMatch
      ? classNumberMatch[0]
      : classMatch
        ? classMatch[1]
        : parenthesizedClassMatch
          ? parenthesizedClassMatch[1]
          : "";

    if (!section || !classNumber) return null;
    return {
      course_code: `${courseMatch[1]}${courseMatch[2]}`.toUpperCase(),
      section: section.toUpperCase(),
      class_number: classNumber
    };
  }

  function selectedTerm(documentObject) {
    const selectors = [
      "select[id*='STRM'] option:checked",
      "[id*='SSR_TERM_DESCR']",
      "[id*='TERM_DESCR']",
      "[data-term-label]"
    ];
    for (const selector of selectors) {
      const element = documentObject.querySelector(selector);
      const text = normalizeText(element && (element.textContent || element.value));
      if (text) return text.slice(0, 100);
    }
    const pageText = normalizeText(documentObject.body && documentObject.body.textContent);
    const textMatch = pageText.match(/\b(20[0-9]{2}-[0-9]{2})\s+Sem(?:ester)?\s+([12])\b/i);
    if (textMatch) return `${textMatch[1]} Sem ${textMatch[2]}`;
    return null;
  }

  function availableTerms(documentObject) {
    const pageText = normalizeText(documentObject.body && documentObject.body.textContent);
    const terms = [];
    const seen = new Set();
    const pattern = /\b(20[0-9]{2}-[0-9]{2})\s+Sem(?:ester)?\s+([12])\b/gi;
    for (const match of pageText.matchAll(pattern)) {
      const term = `${match[1]} Sem ${match[2]}`;
      if (!seen.has(term)) {
        seen.add(term);
        terms.push(term);
      }
    }
    return terms.slice(0, 10);
  }

  function classifyPage(documentObject, url) {
    const bodyText = normalizeText(documentObject.body && documentObject.body.textContent).toLowerCase();
    const hasPassword = Boolean(documentObject.querySelector("input[type='password']"));
    let loginUrl = false;
    try {
      const parsed = new URL(url);
      loginUrl = parsed.pathname.toLowerCase().includes("login") ||
        parsed.pathname.toLowerCase().endsWith("z_signon.jsp") ||
        parsed.searchParams.get("cmd")?.toLowerCase() === "login" ||
        parsed.searchParams.get("errorPg")?.toLowerCase() === "err";
    } catch (_error) {
      // Synthetic documents and incomplete frame URLs are classified from DOM evidence.
    }
    if (hasPassword || loginUrl) return "login";
    if (/access denied|not authorized|session (?:has )?expired/.test(bodyText)) return "blocked";
    if (/select term/.test(bodyText) && /select a term then select continue/.test(bodyText)) {
      return "term_selection";
    }
    if (
      (/exam(?:ination)? date/.test(bodyText) && /exam(?:ination)? time|start time/.test(bodyText)) ||
      (/examination timetables?/.test(bodyText) && /not (?:yet )?published|no exam/.test(bodyText))
    ) return "exam_schedule";
    // The left SIS navigation frame always contains the text "Enrollment Add
    // Classes". It is therefore not sufficient evidence that the main cart
    // page is open. The target page itself always exposes a course-list/cart
    // marker, which avoids treating the menu frame as a successful target.
    if (/temporary course list|enrollment shopping cart|course shopping cart/.test(bodyText)) {
      return "cart";
    }
    if (/enrollment status|class schedule/.test(bodyText)) return "status";
    if (/student center|manage classes/.test(bodyText) || /studentcenter/i.test(url)) return "home";
    // Legacy PeopleSoft frames can retain hidden sign-in text after SSO.
    // It is login evidence only when no verified functional marker matched above.
    if (/\bsign in\b|\blog in\b/.test(bodyText.slice(0, 2500))) return "login";
    return "unknown";
  }

  function courseKey(course) {
    return `${course.course_code}|${course.section}|${course.class_number}`;
  }

  function addUniqueCourse(target, seen, course) {
    if (!course) return;
    const key = courseKey(course);
    if (seen.has(key)) return;
    seen.add(key);
    target.push(course);
  }

  function findShortMarker(documentObject, pattern) {
    const elements = documentObject.querySelectorAll("h1, h2, h3, h4, th, td, span, div");
    return Array.from(elements).find((element) => {
      const text = normalizeText(element.textContent);
      return text.length > 0 && text.length < 180 && pattern.test(text);
    }) || null;
  }

  function isAfter(element, marker) {
    if (!marker || typeof marker.compareDocumentPosition !== "function") return false;
    return Boolean(marker.compareDocumentPosition(element) & 4);
  }

  function createCourseBoundaries(documentObject) {
    const cartMarker =
      findShortMarker(
        documentObject,
        /\b20[0-9]{2}-[0-9]{2}\s+sem(?:ester)?\s+[12]\s+temporary course list\b/i
      ) || findShortMarker(documentObject, /temporary course list/i);
    // Deliberately require the dated "My ... Class Schedule" heading. The
    // generic phrase also appears in the left navigation as Class Schedule Planner.
    const scheduleMarker = findShortMarker(
      documentObject,
      /\bmy\s+20[0-9]{2}-[0-9]{2}\s+sem(?:ester)?\s+[12]\s+class schedule\b/i
    );
    const cartContainer = cartMarker && typeof cartMarker.closest === "function"
      ? cartMarker.closest("table")
      : null;
    const scheduleContainer = scheduleMarker && typeof scheduleMarker.closest === "function"
      ? scheduleMarker.closest("table")
      : null;
    return { cartMarker, scheduleMarker, cartContainer, scheduleContainer };
  }

  function classifyCourseRegion(element, boundaries) {
    const { cartMarker, scheduleMarker, cartContainer, scheduleContainer } = boundaries;
    const scheduleContainerIsSpecific = scheduleContainer &&
      typeof scheduleContainer.contains === "function" &&
      (!cartMarker || !scheduleContainer.contains(cartMarker));
    if (scheduleContainerIsSpecific && scheduleContainer.contains(element)) return "schedule";

    const cartContainerIsSpecific = cartContainer &&
      typeof cartContainer.contains === "function" &&
      (!scheduleMarker || !cartContainer.contains(scheduleMarker));
    if (cartContainerIsSpecific && cartContainer.contains(element)) return "temporary";

    if (scheduleMarker && isAfter(element, scheduleMarker)) return "schedule";
    if (cartMarker && isAfter(element, cartMarker)) return "temporary";
    return "unclassified";
  }

  function extractCartCourseGroups(documentObject, boundaries = null) {
    const courseBoundaries = boundaries || createCourseBoundaries(documentObject);
    const groups = { temporary: [], schedule: [], unclassified: [] };
    const seen = {
      temporary: new Set(),
      schedule: new Set(),
      unclassified: new Set()
    };
    for (const link of documentObject.querySelectorAll("a")) {
      const text = normalizeText(link.textContent);
      if (text.length === 0 || text.length > 120) continue;
      if (!COURSE_SECTION_PATTERN.test(text) || !/\([0-9]{3,8}\)/.test(text)) continue;
      const course = parseCourseRow([text], ["Class"]);
      if (!course) continue;
      const row = typeof link.closest === "function" ? link.closest("tr") : null;
      const region = classifyCourseRegion(row || link, courseBoundaries);
      addUniqueCourse(groups[region], seen[region], course);
    }
    return groups;
  }

  function scheduleMeetingKey(meeting) {
    return [meeting.course_code, meeting.section, meeting.class_number || "", meeting.weekday,
      meeting.start_time, meeting.end_time, meeting.room || ""].join("|");
  }

  function extractScheduleMeetings(documentObject, boundaries = null) {
    const courseBoundaries = boundaries || createCourseBoundaries(documentObject);
    const meetings = [];
    const seen = new Set();
    for (const link of documentObject.querySelectorAll("a")) {
      const linkText = normalizeText(link.textContent);
      if (!COURSE_SECTION_PATTERN.test(linkText) || !/\([0-9]{3,8}\)/.test(linkText)) continue;
      const row = typeof link.closest === "function" ? link.closest("tr") : null;
      if (!row || classifyCourseRegion(row, courseBoundaries) !== "schedule") continue;
      const course = parseCourseRow([linkText], ["Class"]);
      if (!course) continue;
      const cells = Array.from(row.querySelectorAll(":scope > th, :scope > td"));
      const dayTimeIndex = cells.findIndex((cell) => parseDayTimes(cell.textContent).length > 0);
      if (dayTimeIndex < 0) continue;
      const parsedTimes = parseDayTimes(cells[dayTimeIndex].textContent);
      const roomLines = dayTimeIndex + 1 < cells.length
        ? textLines(cells[dayTimeIndex + 1].innerText || cells[dayTimeIndex + 1].textContent)
        : [];
      parsedTimes.forEach((time, index) => {
        const room = roomLines[index] || (roomLines.length === 1 ? roomLines[0] : null);
        const meeting = { ...course, ...time, room };
        const key = scheduleMeetingKey(meeting);
        if (!seen.has(key)) {
          seen.add(key);
          meetings.push(meeting);
        }
      });
    }
    return meetings.slice(0, 1000);
  }

  function normalizedExamDate(value) {
    const iso = normalizeText(value).match(/\b(20[0-9]{2})[-\/]([01]?[0-9])[-\/]([0-3]?[0-9])\b/);
    if (iso) return `${iso[1]}-${String(iso[2]).padStart(2, "0")}-${String(iso[3]).padStart(2, "0")}`;
    const local = normalizeText(value).match(/\b([0-3]?[0-9])[-\/]([01]?[0-9])[-\/](20[0-9]{2})\b/);
    if (local) return `${local[3]}-${String(local[2]).padStart(2, "0")}-${String(local[1]).padStart(2, "0")}`;
    return null;
  }

  function extractExamEntries(documentObject) {
    const entries = [];
    const seen = new Set();
    for (const row of documentObject.querySelectorAll("tr")) {
      const cells = Array.from(row.querySelectorAll(":scope > th, :scope > td"));
      const values = cells.map((cell) => normalizeText(cell.textContent));
      const rowText = normalizeText(values.join(" "));
      const combinedCourseMatch = rowText.match(COURSE_SECTION_PATTERN);
      const courseMatch = combinedCourseMatch || rowText.match(COURSE_PATTERN);
      const date = normalizedExamDate(rowText);
      if (!courseMatch || !date) continue;
      const timeMatch = rowText.match(/\b([0-2][0-9]:[0-5][0-9])\s*[-\u2010-\u2015]\s*([0-2][0-9]:[0-5][0-9])\b/);
      const headers = cells.map((cell) => normalizeHeader(cell.getAttribute?.("data-header") || ""));
      const venueIndex = headers.findIndex((header) => /venue|room|location/.test(header));
      const seatIndex = headers.findIndex((header) => /seat/.test(header));
      const entry = {
        course_code: `${courseMatch[1]}${courseMatch[2]}`.toUpperCase(),
        section: combinedCourseMatch ? combinedCourseMatch[3].toUpperCase() : "ALL",
        exam_date: date,
        start_time: timeMatch ? timeMatch[1] : null,
        end_time: timeMatch ? timeMatch[2] : null,
        venue: venueIndex >= 0 ? values[venueIndex] || null : null,
        seat: seatIndex >= 0 ? values[seatIndex] || null : null
      };
      const key = JSON.stringify(entry);
      if (!seen.has(key)) {
        seen.add(key);
        entries.push(entry);
      }
    }
    return entries.slice(0, 200);
  }

  function examPublicationState(documentObject, pageKind, entries) {
    if (pageKind !== "exam_schedule") return "unavailable";
    const text = normalizeText(documentObject.body && documentObject.body.textContent).toLowerCase();
    if (/not (?:yet )?published|no exam(?:ination)? (?:schedule|timetable)/.test(text)) {
      return entries.length ? "partially_published" : "not_published";
    }
    return entries.length ? "published" : "not_published";
  }

  function extractCourses(documentObject, pageKind = "status", boundaries = null) {
    if (pageKind === "cart") {
      return extractCartCourseGroups(documentObject, boundaries).temporary.slice(0, 200);
    }

    const courses = [];
    const seen = new Set();
    const processedRows = new Set();
    for (const table of documentObject.querySelectorAll("table")) {
      const headers = Array.from(table.querySelectorAll("thead th, tr:first-child th")).map(
        (cell) => cell.textContent
      );
      for (const row of table.querySelectorAll("tbody tr, tr")) {
        if (processedRows.has(row)) continue;
        processedRows.add(row);
        const cells = Array.from(row.querySelectorAll(":scope > th, :scope > td")).map(
          (cell) => cell.textContent
        );
        if (!cells.length) continue;
        addUniqueCourse(courses, seen, parseCourseRow(cells, headers));
      }
    }
    return courses.slice(0, 200);
  }

  function parserDiagnostics(documentObject, boundaries, groups) {
    return {
      parser_version: "0.3.1",
      table_count: documentObject.querySelectorAll("table").length,
      row_count: documentObject.querySelectorAll("tr").length,
      cart_marker_found: Boolean(boundaries.cartMarker),
      schedule_marker_found: Boolean(boundaries.scheduleMarker),
      temporary_candidate_count: groups.temporary.length,
      schedule_candidate_count: groups.schedule.length,
      unclassified_candidate_count: groups.unclassified.length,
      unclassified_courses: groups.unclassified.slice(0, 10)
    };
  }

  function inspectDocument(documentObject, locationObject) {
    const pageKind = classifyPage(documentObject, locationObject.href || "");
    const terms = pageKind === "term_selection" ? availableTerms(documentObject) : [];
    const boundaries = createCourseBoundaries(documentObject);
    const groups = pageKind === "cart"
      ? extractCartCourseGroups(documentObject, boundaries)
      : { temporary: [], schedule: [], unclassified: [] };
    if (pageKind === "status") {
      groups.schedule = extractCourses(documentObject, pageKind, boundaries);
    }
    const scheduleMeetings = extractScheduleMeetings(documentObject, boundaries);
    const examEntries = extractExamEntries(documentObject);
    const primaryCourses = pageKind === "cart" ? groups.temporary : groups.schedule;
    const sisMarker = Boolean(
      documentObject.querySelector("[id*='DERIVED_SSS'], [id*='SSR_'], form[action*='psp']")
    );
    const authenticatedPage = [
      "term_selection", "cart", "status", "home", "exam_schedule"
    ].includes(pageKind);
    return {
      bound: true,
      origin: SIS_ORIGIN,
      logged_in: pageKind === "login" || pageKind === "blocked"
        ? false
        : authenticatedPage || sisMarker
          ? true
          : null,
      page_kind: pageKind,
      term_label: pageKind === "term_selection" ? null : selectedTerm(documentObject),
      available_terms: terms,
      course_count: primaryCourses.length,
      temporary_course_count: groups.temporary.length,
      schedule_course_count: groups.schedule.length,
      visible_courses: groups.temporary,
      temporary_courses: groups.temporary,
      schedule_courses: groups.schedule,
      schedule_meetings: scheduleMeetings,
      exam_publication_state: examPublicationState(documentObject, pageKind, examEntries),
      exam_entries: examEntries,
      diagnostics: parserDiagnostics(documentObject, boundaries, groups)
    };
  }

  function snapshotScore(snapshot) {
    const kindScore = {
      cart: 500,
      term_selection: 450,
      status: 400,
      exam_schedule: 425,
      home: 300,
      blocked: 250,
      login: 200,
      unknown: 0
    };
    return (kindScore[snapshot.page_kind] || 0) +
      (snapshot.term_label ? 40 : 0) +
      Math.min(snapshot.course_count, 20);
  }

  function chooseBestSnapshot(snapshots) {
    const best = snapshots.reduce(
      (best, candidate) => snapshotScore(candidate) > snapshotScore(best) ? candidate : best
    );
    const bestIsAuthenticated = [
      "term_selection", "cart", "status", "home", "exam_schedule"
    ].includes(best.page_kind);
    const loggedIn = bestIsAuthenticated || snapshots.some((snapshot) => snapshot.logged_in === true)
      ? true
      : snapshots.some((snapshot) => snapshot.logged_in === false)
        ? false
        : null;
    return { ...best, logged_in: loggedIn };
  }

  function collectSameOriginDocuments(documentObject) {
    const documents = [documentObject];
    const seen = new Set(documents);
    for (let index = 0; index < documents.length; index += 1) {
      const current = documents[index];
      for (const frame of current.querySelectorAll("iframe, frame")) {
        try {
          const child = frame.contentDocument;
          if (child && !seen.has(child)) {
            seen.add(child);
            documents.push(child);
          }
        } catch (_error) {
          // Cross-origin frames are deliberately ignored.
        }
      }
    }
    return documents;
  }

  function inspect(documentObject, locationObject) {
    if (!locationObject || locationObject.origin !== SIS_ORIGIN) {
      throw new Error("The active page is not the allowed HKU SIS origin.");
    }
    const snapshots = collectSameOriginDocuments(documentObject).map((candidate) =>
      inspectDocument(candidate, locationObject)
    );
    const best = chooseBestSnapshot(snapshots);
    return {
      ...best,
      diagnostics: { ...best.diagnostics, document_count: snapshots.length }
    };
  }

  const api = {
    chooseBestSnapshot,
    classifyPage,
    collectSameOriginDocuments,
    extractCartCourseGroups,
    extractCourses,
    extractScheduleMeetings,
    extractExamEntries,
    examPublicationState,
    inspect,
    normalizeText,
    parseDayTimes,
    parseCourseRow,
    selectedTerm,
    availableTerms
  };
  root.HKUSISParser = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof self !== "undefined" ? self : this);
