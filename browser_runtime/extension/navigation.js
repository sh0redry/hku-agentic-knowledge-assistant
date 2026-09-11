(function (root) {
  "use strict";

  const LEGACY_PORTAL_ORIGIN = "https://hkuportal.hku.hk";
  const PORTAL_ORIGINS = new Set([
    LEGACY_PORTAL_ORIGIN,
    "https://studentportal.hku.hk"
  ]);
  const SIS_ORIGIN = "https://sis-main.hku.hk";
  const SIS_ENTRY_LABELS = new Set([
    "sis",
    "student information system",
    "student information system (sis)"
  ]);
  const SIS_SIGNON_PATH = "/sisprod/z_signon.jsp";
  const ENROLLMENT_COMPONENT = "SA_LEARNER_SERVICES.SSR_SSENRL_CART.GBL";
  const TERM_LABEL_PATTERN = /^20[0-9]{2}-[0-9]{2}\s+Sem\s+[12]$/i;
  const ENROLLMENT_URL =
    `${SIS_ORIGIN}/psp/sisprod/EMPLOYEE/PSFT_CS/c/${ENROLLMENT_COMPONENT}` +
    "?pslnkid=Z_HC_SSR_SSENRL_CART_LNK" +
    "&FolderPath=PORTAL_ROOT_OBJECT.Z_SIS_MENU.Z_ENROLLMENT.Z_HC_SSR_SSENRL_CART_LNK" +
    "&IsFolder=false&IgnoreParamTempl=FolderPath,IsFolder";

  function normalizeText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function normalizedLabel(element) {
    return normalizeText(
      element?.getAttribute?.("aria-label") ||
      element?.getAttribute?.("title") ||
      element?.textContent
    ).toLowerCase().replace(/^icon\s+/, "");
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
          // Cross-origin frames are never inspected or controlled.
        }
      }
    }
    return documents;
  }

  function clickableElements(documentObject) {
    return Array.from(documentObject.querySelectorAll("a, button, [role='link']"));
  }

  function safePortalDestination(element, locationObject) {
    const rawHref = element?.getAttribute?.("href");
    if (!rawHref || /^javascript:/i.test(rawHref)) return null;
    try {
      const destination = new URL(rawHref, locationObject.href);
      if (destination.protocol !== "https:") return null;
      if (!PORTAL_ORIGINS.has(destination.origin) && destination.origin !== SIS_ORIGIN) return null;
      return destination;
    } catch (_error) {
      return null;
    }
  }

  function portalSisCandidates(documentObject, locationObject) {
    const candidates = [];
    for (const documentCandidate of collectSameOriginDocuments(documentObject)) {
      for (const element of clickableElements(documentCandidate)) {
        const label = normalizedLabel(element);
        if (!SIS_ENTRY_LABELS.has(label)) continue;
        const destination = safePortalDestination(element, locationObject);
        if (!destination || !isApprovedSisEntry(destination)) continue;
        candidates.push({ element, label, destination });
      }
    }
    return candidates;
  }

  function isApprovedSisEntry(destination) {
    if (destination.origin === SIS_ORIGIN) {
      return destination.pathname.toLowerCase() === SIS_SIGNON_PATH;
    }
    return destination.origin === LEGACY_PORTAL_ORIGIN &&
      destination.pathname.toLowerCase() === "/ssoaccess.html" &&
      destination.searchParams.get("service")?.toLowerCase() === "sis";
  }

  function classifyPortalPage(documentObject, locationObject) {
    if (!locationObject || !PORTAL_ORIGINS.has(locationObject.origin)) return "unknown";
    const bodyText = normalizeText(documentObject.body?.textContent).toLowerCase();
    if (documentObject.querySelector("input[type='password']") || /log in with uid|sign in/.test(bodyText)) {
      return "portal_login";
    }
    if (/access denied|not authorized|session (?:has )?expired/.test(bodyText)) return "blocked";
    if (
      portalSisCandidates(documentObject, locationObject).length > 0 ||
      /dashboard|my page|logout/.test(bodyText)
    ) {
      return "portal_home";
    }
    return "unknown";
  }

  function inspectPortal(documentObject, locationObject) {
    if (!locationObject || !PORTAL_ORIGINS.has(locationObject.origin)) {
      throw new Error("The active page is not the allowed HKU Portal origin.");
    }
    const pageKind = classifyPortalPage(documentObject, locationObject);
    const candidates = portalSisCandidates(documentObject, locationObject);
    return {
      bound: true,
      origin: locationObject.origin,
      logged_in: pageKind === "portal_login" ? false : pageKind === "portal_home" ? true : null,
      page_kind: pageKind,
      term_label: null,
      course_count: 0,
      temporary_course_count: 0,
      schedule_course_count: 0,
      navigation_diagnostics: {
        parser_version: "0.4.4",
        sis_entry_candidate_count: candidates.length,
        sis_entry_available: candidates.length > 0,
        candidate_labels: [...new Set(candidates.map((candidate) => candidate.label))].slice(0, 5)
      }
    };
  }

  function uniqueDestinationCandidate(candidates, errorPrefix) {
    const destinations = new Map();
    for (const candidate of candidates) {
      const key = candidate.destination.href;
      if (!destinations.has(key)) destinations.set(key, candidate);
    }
    if (destinations.size === 0) {
      const error = new Error(`${errorPrefix} was not found on the verified page.`);
      error.code = "NAVIGATION_TARGET_NOT_FOUND";
      throw error;
    }
    if (destinations.size > 1) {
      const error = new Error(`${errorPrefix} is ambiguous; navigation stopped safely.`);
      error.code = "NAVIGATION_TARGET_AMBIGUOUS";
      throw error;
    }
    return [...destinations.values()][0];
  }

  function deferNavigation(action, scheduler) {
    const schedule = scheduler || ((callback) => setTimeout(callback, 50));
    schedule(action);
  }

  function termLabelFromText(value) {
    const match = normalizeText(value).match(
      /\b(20[0-9]{2}-[0-9]{2})\s+Sem(?:ester)?\s+([12])\b/i
    );
    return match ? `${match[1]} Sem ${match[2]}` : null;
  }

  function radioTermLabel(radio) {
    const values = [
      radio?.getAttribute?.("aria-label"),
      radio?.getAttribute?.("title")
    ];
    if (radio?.labels) {
      for (const label of Array.from(radio.labels)) values.push(label.textContent);
    }
    const row = radio?.closest?.("tr");
    if (row) values.push(row.textContent);
    for (const value of values) {
      const term = termLabelFromText(value);
      if (term) return term;
    }
    return null;
  }

  function termSelectionCandidates(documentObject) {
    const candidates = [];
    for (const documentCandidate of collectSameOriginDocuments(documentObject)) {
      for (const radio of documentCandidate.querySelectorAll("input[type='radio']")) {
        const termLabel = radioTermLabel(radio);
        if (termLabel) candidates.push({ radio, termLabel, documentObject: documentCandidate });
      }
    }
    return candidates;
  }

  function continueCandidates(documentObject) {
    return Array.from(
      documentObject.querySelectorAll("button, input[type='button'], input[type='submit'], a")
    ).filter((element) => {
      const label = normalizeText(
        element?.getAttribute?.("aria-label") ||
        element?.getAttribute?.("title") ||
        element?.value ||
        element?.textContent
      ).toLowerCase();
      return label === "continue";
    });
  }

  function selectTerm(documentObject, locationObject, requestedTerm, inspectSis, scheduler) {
    if (!locationObject || locationObject.origin !== SIS_ORIGIN) {
      const error = new Error("The active page is not the allowed HKU SIS origin.");
      error.code = "WRONG_SIS_ORIGIN";
      throw error;
    }
    const normalizedTerm = normalizeText(requestedTerm);
    if (!TERM_LABEL_PATTERN.test(normalizedTerm)) {
      const error = new Error("A valid HKU SIS term label is required.");
      error.code = "INVALID_TERM_LABEL";
      throw error;
    }
    const snapshot = inspectSis(documentObject, locationObject);
    if (snapshot.logged_in !== true) {
      const error = new Error("The SIS session is not authenticated.");
      error.code = "SIS_LOGIN_REQUIRED";
      throw error;
    }
    if (snapshot.page_kind !== "term_selection") {
      const error = new Error("SIS is not showing the Select Term page.");
      error.code = "WRONG_SIS_PAGE";
      throw error;
    }
    const matches = termSelectionCandidates(documentObject).filter(
      (candidate) => candidate.termLabel.toLowerCase() === normalizedTerm.toLowerCase()
    );
    if (matches.length === 0) {
      const error = new Error(`Requested term '${normalizedTerm}' is not available on the SIS page.`);
      error.code = "TERM_NOT_AVAILABLE";
      throw error;
    }
    if (matches.length > 1) {
      const error = new Error(`Requested term '${normalizedTerm}' is ambiguous; navigation stopped safely.`);
      error.code = "TERM_SELECTION_AMBIGUOUS";
      throw error;
    }
    const continueButtons = continueCandidates(matches[0].documentObject);
    if (continueButtons.length !== 1) {
      const error = new Error("The Select Term Continue control is missing or ambiguous.");
      error.code = continueButtons.length === 0
        ? "NAVIGATION_TARGET_NOT_FOUND"
        : "NAVIGATION_TARGET_AMBIGUOUS";
      throw error;
    }
    deferNavigation(() => {
      matches[0].radio.click();
      continueButtons[0].click();
    }, scheduler);
    return {
      navigation_started: true,
      selected_term_label: normalizedTerm,
      sis_write_requests_sent: 0
    };
  }

  function openSisFromPortal(documentObject, locationObject, scheduler) {
    const snapshot = inspectPortal(documentObject, locationObject);
    if (snapshot.logged_in !== true) {
      const error = new Error("Complete HKU Portal login and MFA before opening SIS.");
      error.code = "PORTAL_LOGIN_REQUIRED";
      throw error;
    }
    const candidate = uniqueDestinationCandidate(
      portalSisCandidates(documentObject, locationObject),
      "The Student Information System entry"
    );
    deferNavigation(() => candidate.element.click(), scheduler);
    return {
      read_only: true,
      navigation_only: true,
      sis_write_requests_sent: 0,
      source_origin: locationObject.origin,
      target_origin: candidate.destination.origin,
      navigation_started: true,
      portal_entry_clicked: true
    };
  }

  function openEnrollmentAddClasses(documentObject, locationObject, inspectSis, scheduler) {
    if (!locationObject || locationObject.origin !== SIS_ORIGIN) {
      const error = new Error("The active page is not the allowed HKU SIS origin.");
      error.code = "WRONG_SIS_ORIGIN";
      throw error;
    }
    const snapshot = inspectSis(documentObject, locationObject);
    if (snapshot.logged_in !== true) {
      const error = new Error("The SIS session is not authenticated.");
      error.code = "SIS_LOGIN_REQUIRED";
      throw error;
    }
    if (snapshot.page_kind === "cart") {
      return { navigation_started: false, already_at_target: true };
    }
    if (typeof locationObject.assign !== "function") {
      const error = new Error("The verified SIS page cannot start fixed-route navigation.");
      error.code = "PAGE_NAVIGATION_UNAVAILABLE";
      throw error;
    }
    deferNavigation(() => locationObject.assign(ENROLLMENT_URL), scheduler);
    return {
      navigation_started: true,
      already_at_target: false,
      target_origin: SIS_ORIGIN,
      target_component: ENROLLMENT_COMPONENT
    };
  }

  const api = {
    classifyPortalPage,
    inspectPortal,
    normalizeText,
    openEnrollmentAddClasses,
    openSisFromPortal,
    portalSisCandidates,
    selectTerm,
    termSelectionCandidates
  };
  root.HKUNavigation = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof self !== "undefined" ? self : this);
