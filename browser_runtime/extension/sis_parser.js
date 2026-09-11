(function (root) {
  "use strict";

  const SIS_ORIGIN = "https://sis-main.hku.hk";
  const COURSE_PATTERN = /\b([A-Z]{2,8})\s*([0-9]{3,5}[A-Z]?)\b/i;
  const COURSE_SECTION_PATTERN =
    /\b([A-Z]{2,8})\s*([0-9]{3,5}[A-Z]?)\s*[-\u2010-\u2015]\s*([A-Z0-9-]{1,20})\b/i;
  const CLASS_PATTERN = /\bclass\s*(?:nbr|number|no\.?|#)\s*:?\s*([0-9]{3,8})\b/i;
  const SECTION_PATTERN = /\bsection\s*:?\s*([A-Z0-9-]{1,20})\b/i;

  function normalizeText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function normalizeHeader(value) {
    return normalizeText(value).toLowerCase().replace(/[^a-z0-9]+/g, " ");
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
    if (hasPassword || /sign in|log in/.test(bodyText.slice(0, 2500))) return "login";
    if (/access denied|not authorized|session (?:has )?expired/.test(bodyText)) return "blocked";
    if (/select term/.test(bodyText) && /select a term then select continue/.test(bodyText)) {
      return "term_selection";
    }
    // The left SIS navigation frame always contains the text "Enrollment Add
    // Classes". It is therefore not sufficient evidence that the main cart
    // page is open. The target page itself always exposes a course-list/cart
    // marker, which avoids treating the menu frame as a successful target.
    if (/temporary course list|enrollment shopping cart|course shopping cart/.test(bodyText)) {
      return "cart";
    }
    if (/enrollment status|class schedule/.test(bodyText)) return "status";
    if (/student center|manage classes/.test(bodyText) || /studentcenter/i.test(url)) return "home";
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
      parser_version: "0.2.2",
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
    const primaryCourses = pageKind === "cart" ? groups.temporary : groups.schedule;
    const sisMarker = Boolean(
      documentObject.querySelector("[id*='DERIVED_SSS'], [id*='SSR_'], form[action*='psp']")
    );
    return {
      bound: true,
      origin: SIS_ORIGIN,
      logged_in: pageKind === "login" ? false : sisMarker ? true : null,
      page_kind: pageKind,
      term_label: pageKind === "term_selection" ? null : selectedTerm(documentObject),
      available_terms: terms,
      course_count: primaryCourses.length,
      temporary_course_count: groups.temporary.length,
      schedule_course_count: groups.schedule.length,
      visible_courses: groups.temporary,
      temporary_courses: groups.temporary,
      schedule_courses: groups.schedule,
      diagnostics: parserDiagnostics(documentObject, boundaries, groups)
    };
  }

  function snapshotScore(snapshot) {
    const kindScore = {
      cart: 500,
      term_selection: 450,
      status: 400,
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
    const loggedIn = snapshots.some((snapshot) => snapshot.logged_in === true)
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
    inspect,
    normalizeText,
    parseCourseRow,
    selectedTerm,
    availableTerms
  };
  root.HKUSISParser = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof self !== "undefined" ? self : this);
