(function (root) {
  "use strict";

  const SIS_ORIGIN = "https://sis-main.hku.hk";
  const COURSE_PATTERN = /\b([A-Z]{2,8})\s*([0-9]{3,5}[A-Z]?)\b/i;
  const COURSE_SECTION_PATTERN =
    /\b([A-Z]{2,8})\s*([0-9]{3,5}[A-Z]?)\s*-\s*([A-Z0-9-]{1,20})\b/i;
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
    const combinedCourseMatch = (courseCell || rowText).match(COURSE_SECTION_PATTERN);
    const courseMatch = combinedCourseMatch || (courseCell || rowText).match(COURSE_PATTERN);
    if (!courseMatch) return null;

    const sectionCell = valueFromColumn(
      normalizedCells,
      normalizedHeaders,
      (header) => header.includes("section") || header === "sec"
    );
    const sectionMatch = (sectionCell || rowText).match(SECTION_PATTERN);
    const section = sectionCell ||
      (combinedCourseMatch ? combinedCourseMatch[3] : sectionMatch ? sectionMatch[1] : "");

    const classCell = valueFromColumn(
      normalizedCells,
      normalizedHeaders,
      (header) => header.includes("class") && /nbr|number|no/.test(header)
    );
    const classMatch = (classCell || rowText).match(CLASS_PATTERN);
    const classNumberMatch = (classCell || "").match(/\b[0-9]{3,8}\b/);
    const parenthesizedClassMatch = (courseCell || rowText).match(/\(([0-9]{3,8})\)/);
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

  function classifyPage(documentObject, url) {
    const bodyText = normalizeText(documentObject.body && documentObject.body.textContent).toLowerCase();
    const hasPassword = Boolean(documentObject.querySelector("input[type='password']"));
    if (hasPassword || /sign in|log in/.test(bodyText.slice(0, 2500))) return "login";
    if (/access denied|not authorized|session (?:has )?expired/.test(bodyText)) return "blocked";
    if (
      /temporary course list|enrollment shopping cart|course shopping cart|enrollment add classes/.test(
        bodyText
      )
    ) {
      return "cart";
    }
    if (/enrollment status|class schedule/.test(bodyText)) return "status";
    if (/student center|manage classes/.test(bodyText) || /studentcenter/i.test(url)) return "home";
    return "unknown";
  }

  function extractCourses(documentObject, pageKind = "status") {
    const bodyText = normalizeText(documentObject.body && documentObject.body.textContent);
    if (pageKind === "cart" && /temporary course list is empty/i.test(bodyText)) return [];

    const courses = [];
    const seen = new Set();
    for (const table of documentObject.querySelectorAll("table")) {
      const headers = Array.from(table.querySelectorAll("thead th, tr:first-child th")).map(
        (cell) => cell.textContent
      );
      for (const row of table.querySelectorAll("tbody tr, tr")) {
        if (pageKind === "cart" && !isInsideTemporaryCourseList(row, documentObject)) continue;
        const cells = Array.from(row.querySelectorAll(":scope > th, :scope > td")).map(
          (cell) => cell.textContent
        );
        if (!cells.length) continue;
        const course = parseCourseRow(cells, headers);
        if (!course) continue;
        const key = `${course.course_code}|${course.section}|${course.class_number}`;
        if (!seen.has(key)) {
          seen.add(key);
          courses.push(course);
        }
      }
    }
    return courses.slice(0, 200);
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

  function isInsideTemporaryCourseList(row, documentObject) {
    const cartMarker = findShortMarker(documentObject, /temporary course list/i);
    if (!cartMarker) return false;
    const scheduleMarker = findShortMarker(documentObject, /class schedule/i);
    return isAfter(row, cartMarker) && (!scheduleMarker || !isAfter(row, scheduleMarker));
  }

  function inspectDocument(documentObject, locationObject) {
    const pageKind = classifyPage(documentObject, locationObject.href || "");
    const courses = pageKind === "cart" || pageKind === "status"
      ? extractCourses(documentObject, pageKind)
      : [];
    const sisMarker = Boolean(
      documentObject.querySelector("[id*='DERIVED_SSS'], [id*='SSR_'], form[action*='psp']")
    );
    return {
      bound: true,
      origin: SIS_ORIGIN,
      logged_in: pageKind === "login" ? false : sisMarker ? true : null,
      page_kind: pageKind,
      term_label: selectedTerm(documentObject),
      course_count: courses.length,
      visible_courses: courses
    };
  }

  function snapshotScore(snapshot) {
    const kindScore = { cart: 500, status: 400, home: 300, blocked: 250, login: 200, unknown: 0 };
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
    return chooseBestSnapshot(snapshots);
  }

  const api = {
    chooseBestSnapshot,
    classifyPage,
    extractCourses,
    inspect,
    normalizeText,
    parseCourseRow,
    selectedTerm
  };
  root.HKUSISParser = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof self !== "undefined" ? self : this);
