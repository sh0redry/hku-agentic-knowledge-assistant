"use strict";

const assert = require("node:assert/strict");
const parser = require("../browser_runtime/extension/portal_notices_parser.js");

function anchor(title, href) {
  return {
    textContent: title,
    parentElement: null,
    getAttribute(name) {
      return name === "href" ? href : null;
    },
    closest() {
      return this.container;
    }
  };
}

function noticeContainer(title, href, date, source) {
  const itemAnchor = anchor(`${title} ${source} ${date}`, href);
  const container = {
    textContent: `${title} ${source} ${date}`,
    querySelectorAll(selector) {
      return selector.includes("a[href]") ? [itemAnchor] : [];
    },
    querySelector(selector) {
      return selector.includes("source") ? { textContent: source } : null;
    }
  };
  itemAnchor.container = container;
  itemAnchor.parentElement = container;
  return { container, itemAnchor };
}

const first = noticeContainer(
  "Closure of Registry Service Counter",
  "/news/registry-counter?noticeId=12345&ticket=secret",
  "2026-06-29",
  "General Services of the Registry"
);
const unsafe = noticeContainer(
  "External tracking headline",
  "https://evil.example/collect",
  "2026-09-08",
  "Unknown"
);
const crossCardAnchor = anchor(
  "Oct 9 Webinar Hong Kong Institute 2026-09-16",
  "/news/oct-9?noticeId=999"
);
crossCardAnchor.container = first.container;
crossCardAnchor.parentElement = {
  textContent: "Oct 9 Webinar Hong Kong Institute 2026-09-16",
  parentElement: first.container,
  querySelectorAll(selector) {
    return selector.includes("a[href]") ? [crossCardAnchor] : [];
  },
  querySelector() {
    return null;
  }
};
const clonedFirstAnchor = anchor(
  "Closure of Registry Service Counter Wrong Unit 2026-09-16",
  "/news/registry-counter?noticeId=12345&ticket=secret"
);
const clonedFirstContainer = {
  textContent: "Closure of Registry Service Counter Wrong Unit 2026-09-16",
  parentElement: first.container,
  querySelectorAll(selector) {
    return selector.includes("a[href]") ? [clonedFirstAnchor] : [];
  },
  querySelector(selector) {
    return selector.includes("source") ? { textContent: "Wrong Unit" } : null;
  }
};
clonedFirstAnchor.parentElement = clonedFirstContainer;
first.container.querySelectorAll = function (selector) {
  return selector.includes("a[href]") ? [crossCardAnchor, clonedFirstAnchor, first.itemAnchor] : [];
};
const documentObject = {
  body: { textContent: "News" },
  querySelectorAll(selector) {
    if (selector.includes("role='heading'")) {
      return [{
        textContent: "News",
        parentElement: {
          textContent: `${first.container.textContent} ${unsafe.container.textContent}`,
          parentElement: null,
          querySelectorAll(innerSelector) {
            if (innerSelector === "a[href]") {
              return [first.itemAnchor, crossCardAnchor, clonedFirstAnchor, unsafe.itemAnchor];
            }
            return [first.container, unsafe.container];
          }
        }
      }];
    }
    return [];
  }
};
const locationObject = {
  href: "https://studentportal.hku.hk/home",
  origin: "https://studentportal.hku.hk"
};

const result = parser.parsePortalNotices(documentObject, locationObject);
assert.equal(result.notices.length, 2);
assert.deepEqual(result.notices[0], {
  title: "Oct 9 Webinar Hong Kong Institute",
  published_date: "2026-09-16",
  source_label: null,
  url: "https://studentportal.hku.hk/news/oct-9",
  url_query_redacted: true
});
assert.deepEqual(result.notices[1], {
  title: "Closure of Registry Service Counter",
  published_date: "2026-06-29",
  source_label: "General Services of the Registry",
  url: "https://studentportal.hku.hk/news/registry-counter",
  url_query_redacted: true
});
assert.equal(result.diagnostics.notice_candidate_count, 4);
assert.equal(result.diagnostics.unparsed_notice_candidate_count, 1);
assert.equal(result.diagnostics.unsafe_notice_url_candidate_count, 1);
assert.equal(result.diagnostics.duplicate_notice_candidate_count, 1);
assert.equal(result.diagnostics.news_marker_found, true);
assert.equal(parser.isoDateFromText("Updated 2026/9/8"), "2026-09-08");

console.log("Portal notice parser synthetic tests passed.");
