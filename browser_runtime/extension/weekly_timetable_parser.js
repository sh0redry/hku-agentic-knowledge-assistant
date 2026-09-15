(function (root) {
  "use strict";

  const ORIGIN = "https://sweb.hku.hk";
  const TARGET_PATH = "/student/servlet/MyWeekly/showTimetable";
  const COURSE_SECTION = /\b([A-Z]{2,8})\s*([0-9]{3,5}[A-Z]?)(?:\s*-\s*\[[A-Z0-9-]{1,20}\])?\s*[-\s]\s*([A-Z0-9-]{1,20})\b/i;
  const COURSE_ONLY = /\b([A-Z]{2,8})\s*([0-9]{3,5}[A-Z]?)\b/i;
  const CLASS_NUMBER = /(?:class\s*(?:nbr|number|no\.?|#)?\s*:?|\()\s*([0-9]{3,8})\)?/i;
  const TERM = /\b(20[0-9]{2}-[0-9]{2})\s+(?:Sem(?:ester)?|Teaching\s+Period)\s*([12])\b/i;
  const WEEKDAYS = {
    mo: "monday", mon: "monday", monday: "monday",
    tu: "tuesday", tue: "tuesday", tues: "tuesday", tuesday: "tuesday",
    we: "wednesday", wed: "wednesday", wednesday: "wednesday",
    th: "thursday", thu: "thursday", thur: "thursday", thurs: "thursday", thursday: "thursday",
    fr: "friday", fri: "friday", friday: "friday",
    sa: "saturday", sat: "saturday", saturday: "saturday",
    su: "sunday", sun: "sunday", sunday: "sunday"
  };

  function normalizeText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function normalizeHeader(value) {
    return normalizeText(value).toLowerCase().replace(/[^a-z0-9]+/g, " ");
  }

  function normalizeTime(raw) {
    const match = normalizeText(raw).match(/\b([0-2]?\d):([0-5]\d)\s*(am|pm)?\b/i);
    if (!match) return null;
    let hour = Number(match[1]);
    const suffix = (match[3] || "").toLowerCase();
    if (hour > 23 || (suffix && (hour < 1 || hour > 12))) return null;
    if (suffix === "am" && hour === 12) hour = 0;
    if (suffix === "pm" && hour !== 12) hour += 12;
    return `${String(hour).padStart(2, "0")}:${match[2]}`;
  }

  function parseTimeRange(value) {
    const text = normalizeText(value);
    const match = text.match(
      /([0-2]?\d:[0-5]\d\s*(?:am|pm)?)\s*[-\u2010-\u2015]\s*([0-2]?\d:[0-5]\d\s*(?:am|pm)?)/i
    );
    if (!match) return null;
    const start = normalizeTime(match[1]);
    const end = normalizeTime(match[2]);
    if (!start || !end || end <= start) return null;
    return { start_time: start, end_time: end };
  }

  function parseWeekday(value) {
    const words = normalizeText(value).toLowerCase().match(/[a-z]+/g) || [];
    for (const word of words) {
      if (WEEKDAYS[word]) return WEEKDAYS[word];
    }
    return null;
  }

  function termLabel(value) {
    const match = normalizeText(value).match(TERM);
    return match ? `${match[1]} Sem ${match[2]}` : null;
  }

  function weekRange(value) {
    const text = normalizeText(value);
    const match = text.match(
      /(?:week|period|date)?\s*:?[ ]*((?:[0-3]?\d[\/\-][01]?\d[\/\-]20\d{2})|(?:20\d{2}[\/\-][01]?\d[\/\-][0-3]?\d))\s*(?:to|[-\u2010-\u2015])\s*((?:[0-3]?\d[\/\-][01]?\d[\/\-]20\d{2})|(?:20\d{2}[\/\-][01]?\d[\/\-][0-3]?\d))/i
    );
    return match ? `${match[1]} - ${match[2]}` : null;
  }

  function termFromWeekRange(value) {
    const range = weekRange(value) || normalizeText(value);
    const first = range.match(
      /\b(?:([0-3]?\d)[\/-]([01]?\d)[\/-](20\d{2})|(20\d{2})[\/-]([01]?\d)[\/-]([0-3]?\d))\b/
    );
    if (!first) return null;
    const year = Number(first[3] || first[4]);
    const month = Number(first[2] || first[5]);
    if (month >= 9 && month <= 12) {
      return `${year}-${String((year + 1) % 100).padStart(2, "0")} Sem 1`;
    }
    if (month >= 1 && month <= 5) {
      return `${year - 1}-${String(year % 100).padStart(2, "0")} Sem 2`;
    }
    return null;
  }

  function valueAt(values, headers, pattern) {
    const index = headers.findIndex((header) => pattern.test(header));
    return index >= 0 && index < values.length ? values[index] : "";
  }

  function parseCourse(value) {
    const text = normalizeText(value);
    const combined = text.match(COURSE_SECTION);
    const course = combined || text.match(COURSE_ONLY);
    if (!course) return null;
    const explicitSection = text.match(/\b(?:section|class)\s*:?\s*([A-Z0-9-]{1,20})\b/i);
    const section = combined?.[3] || explicitSection?.[1];
    if (!section) return null;
    const classNumber = text.match(CLASS_NUMBER)?.[1] || null;
    return {
      course_code: `${course[1]}${course[2]}`.toUpperCase(),
      section: section.toUpperCase(),
      class_number: classNumber
    };
  }

  function parseListRow(row, headers) {
    const cells = Array.from(row.querySelectorAll(":scope > th, :scope > td"));
    const values = cells.map((cell) => normalizeText(cell.innerText || cell.textContent));
    if (!values.length) return [];
    const rowText = normalizeText(values.join(" "));
    const courseText = valueAt(values, headers, /course|class|subject/) || rowText;
    const sectionText = valueAt(values, headers, /section|\bsec\b/);
    const course = parseCourse(`${courseText} ${sectionText}`) || parseCourse(rowText);
    if (!course) return [];
    const dayText = valueAt(values, headers, /day|weekday/) || rowText;
    const timeText = valueAt(values, headers, /time|hour/) || rowText;
    const weekday = parseWeekday(dayText);
    const time = parseTimeRange(timeText);
    if (!weekday || !time) return [];
    const room = valueAt(values, headers, /room|venue|location/) || null;
    return [{ ...course, weekday, ...time, room: room || null }];
  }

  function parseGridRows(table, headers) {
    const weekdayColumns = headers.map(parseWeekday);
    if (weekdayColumns.filter(Boolean).length < 2) return [];
    const meetings = [];
    for (const row of table.querySelectorAll("tr")) {
      const cells = Array.from(row.querySelectorAll(":scope > th, :scope > td"));
      const values = cells.map((cell) => normalizeText(cell.innerText || cell.textContent));
      const rowTime = parseTimeRange(values[0] || "");
      for (let index = 1; index < cells.length; index += 1) {
        const weekday = weekdayColumns[index];
        const text = values[index] || "";
        const course = parseCourse(text);
        const time = parseTimeRange(text) || rowTime;
        if (!weekday || !course || !time) continue;
        const lines = String(cells[index].innerText || cells[index].textContent || "")
          .split(/[\r\n]+/).map(normalizeText).filter(Boolean);
        const room = lines.find((line) => !parseCourse(line) && !parseTimeRange(line)) || null;
        meetings.push({ ...course, weekday, ...time, room });
      }
    }
    return meetings;
  }

  function meetingKey(item) {
    return [item.course_code, item.section, item.class_number || "", item.weekday,
      item.start_time, item.end_time, item.room || ""].join("|");
  }

  function elementText(element) {
    return String(element && (element.innerText || element.textContent) || "");
  }

  function elementRect(element) {
    if (!element || typeof element.getBoundingClientRect !== "function") return null;
    const rect = element.getBoundingClientRect();
    if (!rect || !Number.isFinite(rect.left) || !Number.isFinite(rect.right) ||
        !Number.isFinite(rect.top) || !Number.isFinite(rect.bottom) ||
        rect.right <= rect.left || rect.bottom <= rect.top) return null;
    return rect;
  }

  function findWeekdayHeaders(documentObject) {
    const headers = [];
    for (const element of documentObject.querySelectorAll("th, td, div, span")) {
      const token = normalizeText(elementText(element)).toLowerCase();
      const weekday = WEEKDAYS[token];
      const rect = weekday ? elementRect(element) : null;
      if (!weekday || !rect) continue;
      if (!headers.some((item) => item.weekday === weekday)) {
        headers.push({ weekday, rect });
      }
    }
    return headers;
  }

  function weekdayFromGeometry(element, headers) {
    const rect = elementRect(element);
    if (!rect || !headers.length) return null;
    const center = (rect.left + rect.right) / 2;
    const containing = headers.find((header) => center >= header.rect.left && center <= header.rect.right);
    if (containing) return containing.weekday;
    let closest = null;
    for (const header of headers) {
      const headerCenter = (header.rect.left + header.rect.right) / 2;
      const distance = Math.abs(center - headerCenter);
      const width = header.rect.right - header.rect.left;
      if (distance <= width * 0.75 && (!closest || distance < closest.distance)) {
        closest = { weekday: header.weekday, distance };
      }
    }
    return closest && closest.weekday;
  }

  function cardRoom(rawText) {
    const lines = String(rawText || "").split(/[\r\n]+/).map(normalizeText).filter(Boolean);
    return lines.find((line) =>
      !parseCourse(line) && !parseTimeRange(line) &&
      !/^(?:previous|next)\s+week$/i.test(line)
    ) || null;
  }

  function extractVisualMeetings(documentObject) {
    const headers = findWeekdayHeaders(documentObject);
    if (headers.length < 2) return { meetings: [], candidateCount: 0, unparsedCount: 0 };
    const meetings = [];
    const candidates = new Set();
    const unparsed = new Set();
    const seen = new Set();
    for (const element of documentObject.querySelectorAll("td, div, span, a")) {
      const rawText = elementText(element);
      const text = normalizeText(rawText);
      if (text.length < 8 || text.length > 180) continue;
      const course = parseCourse(text);
      const time = parseTimeRange(text);
      const rect = elementRect(element);
      if (!course || !time || !rect) continue;
      const signature = [course.course_code, course.section, time.start_time, time.end_time,
        Math.round(rect.left), Math.round(rect.top)].join("|");
      candidates.add(signature);
      const weekday = parseWeekday(text) || weekdayFromGeometry(element, headers);
      if (!weekday) { unparsed.add(signature); continue; }
      const item = { ...course, weekday, ...time, room: cardRoom(rawText) };
      const key = meetingKey(item);
      if (!seen.has(key)) { seen.add(key); meetings.push(item); }
    }
    return { meetings, candidateCount: candidates.size, unparsedCount: unparsed.size };
  }

  function extractMeetings(documentObject) {
    const meetings = [];
    const seen = new Set();
    let meetingCandidates = 0;
    for (const table of documentObject.querySelectorAll("table")) {
      const headerCells = Array.from(table.querySelectorAll("thead th, tr:first-child th, tr:first-child td"));
      const headers = headerCells.map((cell) => normalizeHeader(cell.textContent));
      const gridMeetings = parseGridRows(table, headers);
      const isGrid = headers.map(parseWeekday).filter(Boolean).length >= 2;
      const rows = Array.from(table.querySelectorAll("tbody tr, tr"));
      for (const row of rows) {
        const text = normalizeText(row.innerText || row.textContent);
        if (!isGrid && COURSE_ONLY.test(text) && parseTimeRange(text)) meetingCandidates += 1;
        for (const item of isGrid ? [] : parseListRow(row, headers)) {
          const key = meetingKey(item);
          if (!seen.has(key)) { seen.add(key); meetings.push(item); }
        }
      }
      for (const item of gridMeetings) {
        const key = meetingKey(item);
        if (!seen.has(key)) { seen.add(key); meetings.push(item); }
      }
    }
    const visual = extractVisualMeetings(documentObject);
    meetingCandidates += visual.candidateCount;
    for (const item of visual.meetings) {
      const key = meetingKey(item);
      if (!seen.has(key)) { seen.add(key); meetings.push(item); }
    }
    return {
      meetings: meetings.slice(0, 1000),
      meetingCandidates: Math.max(meetingCandidates, meetings.length),
      unparsedCandidates: visual.unparsedCount + Math.max(0, meetingCandidates - visual.candidateCount - meetings.length)
    };
  }

  function inspect(documentObject, locationObject) {
    if (!locationObject || locationObject.origin !== ORIGIN) {
      const error = new Error("The active page is not the allowed HKU weekly timetable origin.");
      error.code = "WRONG_TIMETABLE_ORIGIN";
      throw error;
    }
    const text = normalizeText(documentObject.body && documentObject.body.textContent);
    const lower = text.toLowerCase();
    const hasPassword = Boolean(documentObject.querySelector("input[type='password']"));
    const blocked = /access denied|not authorized|session (?:has )?expired/.test(lower);
    const marker = /my weekly (?:schedule|timetable)|weekly (?:schedule|timetable)/i.test(text) ||
      locationObject.pathname === TARGET_PATH;
    const login = hasPassword || (!marker && /\bsign in\b|\blog in\b/.test(lower.slice(0, 2500)));
    const parsed = marker && !login && !blocked
      ? extractMeetings(documentObject)
      : { meetings: [], meetingCandidates: 0, unparsedCandidates: 0 };
    const visibleWeekRange = weekRange(text);
    const explicitTerm = termLabel(text);
    const inferredTerm = explicitTerm || termFromWeekRange(visibleWeekRange);
    return {
      bound: true,
      origin: ORIGIN,
      logged_in: login || blocked ? false : marker ? true : null,
      page_kind: login ? "login" : blocked ? "blocked" : marker ? "weekly_timetable" : "unknown",
      term_label: inferredTerm,
      week_range: visibleWeekRange,
      meeting_count: parsed.meetings.length,
      meetings: parsed.meetings,
      diagnostics: {
        parser_version: "0.2.1",
        term_detection_method: explicitTerm ? "page_label" : inferredTerm ? "inferred_from_week_start" : "unavailable",
        table_count: documentObject.querySelectorAll("table").length,
        row_count: documentObject.querySelectorAll("tr").length,
        timetable_marker_found: marker,
        meeting_candidate_count: parsed.meetingCandidates,
        parsed_meeting_count: parsed.meetings.length,
        unparsed_candidate_count: parsed.unparsedCandidates
      }
    };
  }

  const api = {
    extractMeetings,
    inspect,
    normalizeText,
    normalizeTime,
    parseCourse,
    parseListRow,
    parseTimeRange,
    parseWeekday,
    termLabel,
    termFromWeekRange,
    weekRange
  };
  root.HKUWeeklyTimetableParser = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof self !== "undefined" ? self : this);
