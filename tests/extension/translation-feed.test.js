"use strict";

/*
 * Phase 3.6 — translation feed tests.
 *
 * The feed is a view over stored results: shell lifecycle, entry content,
 * reading order, deduplication, navigation, active highlighting, fallback and
 * failure presentation, and cleanup. No backend, no OCR, no models.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

const { createFeedEnvironment } = require("./harness.js");

function region(x1, y1, x2, y2, original, translated, status = "ok") {
  return {
    original_text: original,
    translated_text: translated,
    translation_status: status,
    source_language: "ja",
    bbox: { x1, y1, x2, y2 },
  };
}

function payload(regions, { source = "ja", target = "en" } = {}) {
  return {
    api_version: "1",
    source_language: source,
    target_language: target,
    image: { width: 436, height: 654 },
    regions,
  };
}

const threeRegions = [
  region(10, 10, 100, 40, "これはテストです", "This is a test."),
  region(10, 60, 100, 90, "二番目", "Second line."),
  region(10, 120, 100, 150, "三番目", "Third line."),
];

test("the feed shell is created once, collapsed by default", () => {
  const env = createFeedEnvironment();
  assert.equal(env.shell(), null, "nothing is injected before it is needed");

  env.feed.update(env.addImage(), payload(threeRegions));

  assert.ok(env.shell());
  assert.equal(env.shell().dataset.actFeedOpen, "false");
  assert.equal(env.feed.isOpen(), false);
  assert.equal(env.toggleButton().getAttribute("aria-expanded"), "false");
});

test("the open and close controls collapse the panel", () => {
  const env = createFeedEnvironment();
  env.feed.update(env.addImage(), payload(threeRegions));
  const toggle = env.toggleButton();
  const close = env.closeButton();

  toggle.dispatch("click", { preventDefault() {}, stopPropagation() {} });
  assert.equal(env.feed.isOpen(), true);
  assert.equal(env.shell().dataset.actFeedOpen, "true");
  assert.equal(toggle.getAttribute("aria-expanded"), "true");

  close.dispatch("click", { preventDefault() {}, stopPropagation() {} });
  assert.equal(env.feed.isOpen(), false);
  assert.equal(env.shell().dataset.actFeedOpen, "false");
});

test("only one feed shell exists no matter how many updates happen", () => {
  const env = createFeedEnvironment();
  const first = env.addImage();
  const second = env.addImage();

  env.feed.update(first, payload(threeRegions));
  env.feed.update(second, payload(threeRegions));
  env.feed.update(first, payload(threeRegions));

  assert.equal(env.document.querySelectorAll('[data-act-feed="true"]').length, 1);
  assert.equal(env.document.querySelectorAll(".act-feed-toggle").length, 1);
});

test("one successful image creates one entry with one pair per region", () => {
  const env = createFeedEnvironment();
  const image = env.addImage();

  env.feed.update(image, payload(threeRegions));

  assert.equal(env.feed.entryCount(), 1);
  assert.equal(env.feed.regionCountFor(image), 3);
  assert.equal(env.entries().length, 1);

  const originals = env.entries()[0].querySelectorAll(".act-feed-original");
  const translations = env.entries()[0].querySelectorAll(".act-feed-translated");
  assert.deepEqual(
    originals.map((element) => element.textContent),
    ["これはテストです", "二番目", "三番目"],
  );
  assert.deepEqual(
    translations.map((element) => element.textContent),
    ["This is a test.", "Second line.", "Third line."],
  );
});

test("an entry shows the image index, languages, and a status summary only", () => {
  const env = createFeedEnvironment();
  const image = env.addImage();
  env.feed.update(image, payload(threeRegions, { source: "ja", target: "en" }));

  const entry = env.entries()[0];
  assert.equal(entry.querySelector(".act-feed-entry-title").textContent, "Image 1");
  assert.equal(
    entry.querySelector(".act-feed-entry-langs").textContent,
    "Japanese → English",
  );
  assert.equal(
    entry.querySelector(".act-feed-entry-status").textContent,
    "3 regions",
  );

  // Development-only data must not leak into the user-facing feed.
  const text = entry.textContent;
  for (const forbidden of ["request", "ms", "bbox", "cache", "http"]) {
    assert.ok(
      !text.toLowerCase().includes(forbidden),
      `feed entry must not expose ${forbidden}`,
    );
  }
});

test("repeated success reuses the same entry", () => {
  const env = createFeedEnvironment();
  const image = env.addImage();

  env.feed.update(image, payload(threeRegions));
  env.feed.update(image, payload(threeRegions));
  env.feed.update(image, payload([threeRegions[0]]));

  assert.equal(env.feed.entryCount(), 1);
  assert.equal(env.entries().length, 1);
  assert.equal(env.feed.regionCountFor(image), 1);
});

test("entries stay in reading order even when translations finish out of order", () => {
  const env = createFeedEnvironment();
  const imageA = env.addImage({ src: "a.png" });
  const imageB = env.addImage({ src: "b.png" });
  const imageC = env.addImage({ src: "c.png" });

  // Completion order C, A, B.
  env.feed.update(imageC, payload(threeRegions));
  env.feed.update(imageA, payload(threeRegions));
  env.feed.update(imageB, payload(threeRegions));

  assert.deepEqual(
    [...env.feed.elements()].map(
      (element) => element.querySelector(".act-feed-entry-title").textContent,
    ),
    ["Image 1", "Image 2", "Image 3"],
  );
  assert.deepEqual(
    env.entries().map((element) => element.querySelector(".act-feed-original").textContent),
    ["これはテストです", "これはテストです", "これはテストです"],
  );
  // The rendered entry elements themselves are in A, B, C order.
  const titlesOf = (elements) =>
    [...elements]
      .map(
        (element) => element.querySelector(".act-feed-entry-title").textContent,
      )
      .join("|");
  assert.equal(titlesOf(env.feed.elements()), titlesOf(env.entries()));
});

test("an image inserted between existing ones is ordered by DOM position", () => {
  const env = createFeedEnvironment();
  const imageA = env.addImage({ src: "a.png" });
  const imageC = env.addImage({ src: "c.png" });
  env.feed.update(imageA, payload(threeRegions));
  env.feed.update(imageC, payload(threeRegions));

  const imageB = env.addImage({ src: "b.png", connected: false });
  env.document.body.insertBefore(imageB, imageC);
  env.feed.update(imageB, payload(threeRegions));

  assert.deepEqual(
    [...env.feed.elements()].map((element) => element.dataset.actFeedEntry),
    ["true", "true", "true"],
  );
  const titles = env.entries().map(
    (element) => element.querySelector(".act-feed-entry-title").textContent,
  );
  assert.deepEqual(titles, ["Image 1", "Image 2", "Image 3"]);

  // B now sits between A and C in the DOM, so it owns the middle position.
  const ordered = [...env.feed.elements()];
  const bEntry = env.feed.entryFor(imageB);
  assert.equal(ordered.indexOf(bEntry), 1);
});

test("clicking an entry header scrolls only its own image into view", () => {
  const env = createFeedEnvironment();
  const imageA = env.addImage({ src: "a.png" });
  const imageB = env.addImage({ src: "b.png" });
  env.feed.update(imageA, payload(threeRegions));
  env.feed.update(imageB, payload(threeRegions));

  const headerB = env.feed.entryFor(imageB).querySelector(".act-feed-entry-header");
  headerB.dispatch("click", { preventDefault() {}, stopPropagation() {} });

  assert.equal(env.scrollCalls.length, 1);
  assert.equal(env.scrollCalls[0].image, imageB);
  assert.equal(env.scrollCalls[0].options.behavior, "smooth");
  assert.equal(env.scrollCalls[0].options.block, "center");
});

test("a detached image cannot be navigated to", () => {
  const env = createFeedEnvironment();
  const image = env.addImage();
  env.feed.update(image, payload(threeRegions));

  image.remove();
  const header = env.feed.entryFor(image).querySelector(".act-feed-entry-header");
  header.dispatch("click", { preventDefault() {}, stopPropagation() {} });

  assert.equal(env.scrollCalls.length, 0);
});

test("only the current image's entry is highlighted", () => {
  const env = createFeedEnvironment();
  const imageA = env.addImage({ src: "a.png" });
  const imageB = env.addImage({ src: "b.png" });
  env.feed.update(imageA, payload(threeRegions));
  env.feed.update(imageB, payload(threeRegions));

  const observer = env.activityObserver();
  assert.ok(observer, "the feed observes translated images for the active entry");
  assert.deepEqual(observer.targets, [imageA, imageB]);

  observer.enter(imageB);

  assert.equal(
    env.feed.entryFor(imageB).classList.contains("act-feed-entry-active"),
    true,
  );
  assert.equal(
    env.feed.entryFor(imageA).classList.contains("act-feed-entry-active"),
    false,
  );
  assert.equal(env.feed.currentImage(), imageB);

  observer.enter(imageA);
  assert.equal(
    env.feed.entryFor(imageA).classList.contains("act-feed-entry-active"),
    true,
  );
  assert.equal(
    env.feed.entryFor(imageB).classList.contains("act-feed-entry-active"),
    false,
  );
});

test("a fallback region is marked and never presented as English", () => {
  const env = createFeedEnvironment();
  const image = env.addImage();

  env.feed.update(
    image,
    payload([
      region(10, 10, 100, 40, "翻訳済み", "Translated"),
      region(10, 60, 100, 90, "原文のまま", "原文のまま", "fallback"),
    ]),
  );

  const entry = env.entries()[0];
  assert.equal(
    entry.querySelector(".act-feed-entry-status").textContent,
    "2 regions · 1 fallback",
  );
  const fallbackWrapper = entry.querySelector('[data-act-feed-region="fallback"]');
  const fallback = fallbackWrapper.querySelector(".act-feed-translated");
  assert.equal(fallback.textContent, env.api.FALLBACK_NOTE);
  assert.equal(fallback.dataset.actFeedFallback, "true");
});

test("a failed image gets a compact placeholder, not translated content", () => {
  const env = createFeedEnvironment();
  const image = env.addImage();

  env.feed.updateFailed(image, { kind: "backend-network", message: "offline" });

  const entry = env.entries()[0];
  assert.equal(entry.dataset.actFeedState, "error");
  assert.equal(
    entry.querySelector(".act-feed-entry-status").textContent,
    "Translation unavailable",
  );
  assert.equal(entry.querySelectorAll(".act-feed-region").length, 0);
  assert.ok(!entry.textContent.includes("offline"));

  // A later manual success updates the same entry instead of adding another.
  env.feed.update(image, payload(threeRegions));
  assert.equal(env.feed.entryCount(), 1);
  assert.equal(env.entries().length, 1);
  assert.equal(env.entries()[0].dataset.actFeedState, "translated");
  assert.equal(env.feed.regionCountFor(image), 3);
});

test("backend text is rendered literally, never as markup", () => {
  const env = createFeedEnvironment();
  const image = env.addImage();
  const hostile = '<img src=x onerror=alert(1)><script>alert(2)</script>';

  env.feed.update(
    image,
    payload([region(10, 10, 100, 40, hostile, hostile)]),
  );

  const entry = env.entries()[0];
  assert.equal(entry.querySelector(".act-feed-original").textContent, hostile);
  assert.equal(entry.querySelector(".act-feed-translated").textContent, hostile);
  assert.equal(entry.querySelectorAll("script").length, 0);
  assert.equal(entry.querySelectorAll("img").length, 0);
});

test("removing an image removes its entry and renumbers the rest", () => {
  const env = createFeedEnvironment();
  const imageA = env.addImage({ src: "a.png" });
  const imageB = env.addImage({ src: "b.png" });
  env.feed.update(imageA, payload(threeRegions));
  env.feed.update(imageB, payload(threeRegions));
  assert.equal(env.feed.titleFor(imageB), "Image 2");

  assert.equal(env.feed.remove(imageA), true);
  assert.equal(env.feed.entryCount(), 1);
  assert.equal(env.entries().length, 1);
  assert.equal(env.feed.titleFor(imageB), "Image 1");
  assert.equal(env.feed.remove(imageA), false);
});

test("clearing and destroying the feed leave nothing behind", () => {
  const env = createFeedEnvironment();
  const image = env.addImage();
  env.feed.update(image, payload(threeRegions));

  env.feed.clear();
  assert.equal(env.feed.entryCount(), 0);
  assert.equal(env.entries().length, 0);
  assert.ok(env.shell(), "the shell stays until it is destroyed");

  env.feed.update(image, payload(threeRegions));
  env.feed.destroy();
  assert.equal(env.shell(), null);
  assert.equal(env.toggleButton(), null);
  assert.equal(env.feed.entryCount(), 0);
});

test("disabling the feed clears entries and closes the panel", () => {
  const env = createFeedEnvironment();
  const image = env.addImage();
  env.feed.update(image, payload(threeRegions));
  env.feed.setOpen(true);

  env.feed.setEnabled(false);

  assert.equal(env.feed.isOpen(), false);
  assert.equal(env.feed.entryCount(), 0);
  assert.equal(env.entries().length, 0);
});

test("opening after translation shows the stored entries immediately", () => {
  const env = createFeedEnvironment();
  const imageA = env.addImage({ src: "a.png" });
  const imageB = env.addImage({ src: "b.png" });

  env.feed.update(imageA, payload(threeRegions));
  env.feed.update(imageB, payload(threeRegions));
  assert.equal(env.feed.isOpen(), false);

  env.feed.setOpen(true);

  assert.equal(env.feed.isOpen(), true);
  assert.equal(env.entries().length, 2);
  assert.deepEqual(
    env.entries().map(
      (element) => element.querySelector(".act-feed-entry-title").textContent,
    ),
    ["Image 1", "Image 2"],
  );
});
