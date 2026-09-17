(function (root) {
  "use strict";

  const PARSER_VERSION = "0.1.3";
  const DATE_PATTERN = /\b(20\d{2})[-\/.](0?[1-9]|1[0-2])[-\/.](0?[1-9]|[12]\d|3[01])\b/;
  function normalizeText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function isoDateFromText(value) {
    const match = normalizeText(value).match(DATE_PATTERN);
    if (!match) return null;
    const month = String(Number(match[2])).padStart(2, "0");
    const day = String(Number(match[3])).padStart(2, "0");
    return `${match[1]}-${month}-${day}`;
  }

  function safeNoticeUrl(element, locationObject) {
    const href = element?.getAttribute?.("href");
    if (!href || /^javascript:/i.test(href)) return null;
    try {
      const url = new URL(href, locationObject.href);
      const hostname = url.hostname.toLowerCase();
      if (url.protocol !== "https:" || (hostname !== "hku.hk" && !hostname.endsWith(".hku.hk"))) {
        return null;
      }
      url.search = "";
      url.hash = "";
      return url.href;
    } catch (_error) {
      return null;
    }
  }

  function noticeUrlHadQuery(element, locationObject) {
    try {
      return Boolean(new URL(element?.getAttribute?.("href"), locationObject.href).search);
    } catch (_error) {
      return false;
    }
  }

  function noticeUrlIdentity(element, locationObject) {
    const href = element?.getAttribute?.("href");
    if (!href || /^javascript:/i.test(href)) return null;
    try {
      const url = new URL(href, locationObject.href);
      const hostname = url.hostname.toLowerCase();
      if (url.protocol !== "https:" || (hostname !== "hku.hk" && !hostname.endsWith(".hku.hk"))) {
        return null;
      }
      url.hash = "";
      return url.href;
    } catch (_error) {
      return null;
    }
  }

  function cleanTitle(value, publishedDate, source) {
    let title = normalizeText(value);
    title = normalizeText(title.replace(DATE_PATTERN, " "));
    if (source) {
      const escaped = source.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      title = title.replace(new RegExp(`(?:[,\\s]+${escaped})$`, "i"), " ");
    }
    title = normalizeText(title).replace(/[|,;:\-\s]+$/, "").trim();
    return title === publishedDate ? "" : title;
  }

  function newsRoots(documentObject) {
    const roots = new Set(Array.from(documentObject.querySelectorAll(
      "[data-region*='news'], [class*='news-widget'], [class*='newsWidget'], section[class*='news']"
    )));
    for (const heading of documentObject.querySelectorAll("h1, h2, h3, h4, h5, h6, [role='heading']")) {
      if (normalizeText(heading.textContent).toLowerCase() !== "news") continue;
      let current = heading.parentElement;
      for (let depth = 0; current && depth < 4; depth += 1) {
        if (isoDateFromText(current.textContent) && current.querySelectorAll("a[href]").length) {
          roots.add(current);
          break;
        }
        current = current.parentElement;
      }
    }
    return [...roots];
  }

  function candidateContainers(documentObject, locationObject) {
    const candidates = new Set();
    for (const root of newsRoots(documentObject)) {
      for (const anchor of root.querySelectorAll("a[href]")) {
        const label = normalizeText(
          anchor.getAttribute?.("aria-label") ||
          anchor.getAttribute?.("title") ||
          anchor.textContent
        );
        if (/^(more|read more|details?)$/i.test(label)) continue;
        let container = null;
        let current = anchor.parentElement;
        for (let depth = 0; current && depth < 6; depth += 1) {
          if (isoDateFromText(current.textContent)) {
            container = current;
            break;
          }
          current = current.parentElement;
        }
        if (container) candidates.add(container);
      }
    }
    return [...candidates].filter((container) => isoDateFromText(container.textContent));
  }

  function titleAndUrl(container, locationObject) {
    const publishedDate = isoDateFromText(container.textContent);
    const source = sourceLabel(container);
    const selectors = [
      "[class*='title'] a[href]",
      "h1 a[href], h2 a[href], h3 a[href], h4 a[href], h5 a[href]",
      "a[href]"
    ];
    const seen = new Set();
    const candidates = [];
    for (const selector of selectors) {
      for (const element of container.querySelectorAll(selector)) {
        if (seen.has(element)) continue;
        seen.add(element);
        const rawTitle = normalizeText(
          element.getAttribute?.("aria-label") ||
          element.getAttribute?.("title") ||
          element.textContent
        );
        const anchorDate = isoDateFromText(rawTitle);
        if (anchorDate && anchorDate !== publishedDate) continue;
        const title = cleanTitle(rawTitle, publishedDate, source);
        const url = safeNoticeUrl(element, locationObject);
        if (!title || title.length < 6 || /^(more|read more|details?)$/i.test(title) || !url) continue;
        candidates.push({
          title,
          url,
          urlIdentity: noticeUrlIdentity(element, locationObject),
          rawTitle,
          urlQueryRedacted: noticeUrlHadQuery(element, locationObject)
        });
      }
    }
    candidates.sort((left, right) => {
      const leftDateMatch = isoDateFromText(left.rawTitle) === publishedDate ? 1 : 0;
      const rightDateMatch = isoDateFromText(right.rawTitle) === publishedDate ? 1 : 0;
      return rightDateMatch - leftDateMatch || left.title.length - right.title.length;
    });
    return candidates[0] || null;
  }

  function sourceLabel(container) {
    const selectors = [
      "[class*='source']",
      "[class*='department']",
      "[class*='unit']",
      "[class*='category']"
    ];
    for (const selector of selectors) {
      const value = normalizeText(container.querySelector(selector)?.textContent);
      if (value && value.length <= 200) return value;
    }
    return null;
  }

  function parsePortalNotices(documentObject, locationObject) {
    const containers = candidateContainers(documentObject, locationObject);
    const notices = [];
    const seen = new Set();
    const seenUrlIdentities = new Set();
    let unparsed = 0;
    let unsafeUrl = 0;
    for (const container of containers) {
      const publishedDate = isoDateFromText(container.textContent);
      const title = titleAndUrl(container, locationObject);
      if (!publishedDate || !title) {
        unparsed += 1;
        const anchors = Array.from(container.querySelectorAll("a[href]"));
        if (anchors.length && anchors.every((anchor) => !safeNoticeUrl(anchor, locationObject))) unsafeUrl += 1;
        continue;
      }
      const key = `${title.title.toLowerCase()}|${publishedDate}`;
      if ((title.urlIdentity && seenUrlIdentities.has(title.urlIdentity)) || seen.has(key)) continue;
      seen.add(key);
      if (title.urlIdentity) seenUrlIdentities.add(title.urlIdentity);
      notices.push({
        title: title.title,
        published_date: publishedDate,
        source_label: sourceLabel(container),
        url: title.url,
        url_query_redacted: title.urlQueryRedacted
      });
    }
    notices.sort((left, right) =>
      right.published_date.localeCompare(left.published_date) || left.title.localeCompare(right.title)
    );
    return {
      notices,
      diagnostics: {
        parser_version: PARSER_VERSION,
        news_marker_found: /\bnews\b/i.test(normalizeText(documentObject.body?.textContent)),
        notice_candidate_count: containers.length,
        parsed_notice_count: notices.length,
        unparsed_notice_candidate_count: unparsed,
        unsafe_notice_url_candidate_count: unsafeUrl,
        duplicate_notice_candidate_count: containers.length - notices.length - unparsed
      }
    };
  }

  const api = { isoDateFromText, parsePortalNotices, safeNoticeUrl };
  root.HKUPortalNoticesParser = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof self !== "undefined" ? self : this);
