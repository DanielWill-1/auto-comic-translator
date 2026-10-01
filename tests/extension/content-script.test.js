"use strict";

/*
 * Phase 3.4 — content-script integration tests.
 *
 * Runs the real `extension/content.js` with the real `image-detector`,
 * `translation-queue`, and `lazy-observer` modules in the minimal DOM harness.
 * The translation client is stubbed, so no backend and no models are used.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

const { createEnvironment, successResult } = require("./harness.js");

test("candidate images are discovered and registered with the lazy observer", async () => {
  const env = createEnvironment();
  const candidate = env.addImage();
  const icon = env.addImage({
    naturalWidth: 28,
    naturalHeight: 28,
    renderedWidth: 28,
    renderedHeight: 28,
  });
  await env.ready();

  const observer = env.lastIntersectionObserver();
  assert.ok(observer, "expected the lazy observer to be created");
  assert.deepEqual(observer.targets, [candidate]);
  assert.equal(observer.options.rootMargin, "800px 0px");
  assert.equal(candidate.getAttribute("data-act-comic-candidate"), "true");
  assert.equal(icon.getAttribute("data-act-comic-candidate"), null);
  assert.equal(env.translateCalls.length, 0, "nothing translates on page load");
});

test("a near-viewport image is queued once through the shared translation helper", async () => {
  const env = createEnvironment();
  const image = env.addImage();
  await env.ready();

  const observer = env.lastIntersectionObserver();
  observer.enter(image);
  observer.enter(image);
  observer.enter(image);
  await env.flush();

  assert.equal(env.translateCalls.length, 1);
  assert.equal(env.translateCalls[0].sourceLanguage, "ja");
  assert.equal(env.translateCalls[0].backendUrl, "http://127.0.0.1:8000");
  assert.equal(image.getAttribute("data-act-state"), "translated");
  assert.equal(env.fetchCalls.length, 1);
  assert.equal(env.fetchCalls[0].url, "http://127.0.0.1:8080/comic-page.png");

  // Scrolling away and back must not translate again.
  observer.leave(image);
  observer.enter(image);
  await env.flush();
  assert.equal(env.translateCalls.length, 1);

  const [card] = env.cards();
  assert.equal(card.dataset.mode, "auto");
  assert.equal(card.dataset.state, "translated");
});

test("a non-candidate image is never queued", async () => {
  const env = createEnvironment();
  const candidate = env.addImage();
  const icon = env.addImage({
    naturalWidth: 96,
    naturalHeight: 96,
    renderedWidth: 96,
    renderedHeight: 96,
  });
  await env.ready();

  const observer = env.lastIntersectionObserver();
  assert.deepEqual(observer.targets, [candidate]);

  observer.enter(icon);
  await env.flush();

  assert.equal(env.translateCalls.length, 0);
  assert.equal(icon.getAttribute("data-act-state"), null);
  assert.equal(env.cards().length, 0);
});

test("an image detached before its turn is skipped and does not block the queue", async () => {
  let calls = 0;
  let release;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  const env = createEnvironment({
    translate: async () => {
      calls += 1;
      if (calls === 1) {
        await gate;
      }
      return successResult();
    },
  });
  const first = env.addImage();
  const detached = env.addImage();
  const third = env.addImage();
  await env.ready();

  const observer = env.lastIntersectionObserver();
  observer.enter(first);
  await env.flush();
  assert.equal(calls, 1);
  assert.equal(first.getAttribute("data-act-state"), "translating");

  observer.enter(detached);
  observer.enter(third);
  await env.flush();
  assert.equal(calls, 1, "bounded concurrency keeps one request in flight");
  assert.equal(detached.getAttribute("data-act-state"), "queued");
  assert.equal(third.getAttribute("data-act-state"), "queued");

  detached.remove();
  release();
  await env.flush();

  assert.equal(env.translateCalls.length, 2);
  assert.equal(first.getAttribute("data-act-state"), "translated");
  assert.equal(detached.getAttribute("data-act-state"), null);
  assert.equal(third.getAttribute("data-act-state"), "translated");
  assert.equal(env.cards().length, 2);
});

test("a malformed backend response becomes an error state and later images still process", async () => {
  let calls = 0;
  const env = createEnvironment({
    translate: async (call, makeError) => {
      calls += 1;
      if (calls === 1) {
        throw makeError("malformed", "Backend returned a malformed response.");
      }
      return successResult();
    },
  });
  const failing = env.addImage();
  const following = env.addImage();
  await env.ready();

  const observer = env.lastIntersectionObserver();
  observer.enter(failing);
  await env.flush();

  assert.equal(failing.getAttribute("data-act-state"), "error");
  const [errorCard] = env.cards();
  assert.equal(errorCard.dataset.state, "error");

  observer.enter(following);
  await env.flush();

  assert.equal(env.translateCalls.length, 2);
  assert.equal(following.getAttribute("data-act-state"), "translated");
  assert.ok(
    env.logs.some(([level, message]) => level === "warn" && message.includes("lazy translation failed")),
  );
});

test("Alt+Click still triggers a translation and keeps the full development card", async () => {
  const env = createEnvironment();
  const image = env.addImage();
  await env.ready();

  env.click(image);
  await env.flush();
  assert.equal(env.translateCalls.length, 0, "a plain click must not translate");

  env.altClick(image);
  await env.flush();

  assert.equal(env.translateCalls.length, 1);
  assert.equal(image.getAttribute("data-act-state"), "translated");
  const [card] = env.cards();
  assert.equal(card.dataset.mode, "manual");
});

test("Alt+Click does not duplicate an in-flight lazy translation", async () => {
  let release;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  const env = createEnvironment({
    translate: async () => {
      await gate;
      return successResult();
    },
  });
  const image = env.addImage();
  await env.ready();

  env.lastIntersectionObserver().enter(image);
  await env.flush();
  assert.equal(image.getAttribute("data-act-state"), "translating");

  env.altClick(image);
  env.altClick(image);
  await env.flush();
  assert.equal(env.translateCalls.length, 1);

  release();
  await env.flush();
  assert.equal(env.translateCalls.length, 1);
  assert.equal(image.getAttribute("data-act-state"), "translated");
});

test("a completed lazy translation is not retransmitted by a later Alt+Click", async () => {
  const env = createEnvironment();
  const image = env.addImage();
  await env.ready();

  env.lastIntersectionObserver().enter(image);
  await env.flush();
  assert.equal(env.translateCalls.length, 1);
  assert.equal(env.cards()[0].dataset.mode, "auto");

  env.altClick(image);
  await env.flush();

  assert.equal(env.translateCalls.length, 1, "the stored result is reused");
  const [card] = env.cards();
  assert.equal(card.dataset.mode, "manual");
  assert.equal(card.dataset.state, "translated");
});

test("a dynamically inserted image is observed but queued only near the viewport", async () => {
  const env = createEnvironment();
  await env.ready();

  const image = env.addImage({ connected: false });
  env.document.body.append(image);
  env.lastMutationObserver().trigger([
    { type: "childList", addedNodes: [image], target: env.document.body },
  ]);
  await env.flush();

  assert.equal(env.translateCalls.length, 0, "insertion alone must not translate");
  const observer = env.lastIntersectionObserver();
  assert.deepEqual(observer.targets, [image]);

  observer.enter(image);
  await env.flush();
  assert.equal(env.translateCalls.length, 1);
  assert.equal(image.getAttribute("data-act-state"), "translated");
});

test("a lazy-loaded placeholder becomes eligible once the real source arrives", async () => {
  const env = createEnvironment();
  const image = env.addImage({
    complete: false,
    naturalWidth: 0,
    naturalHeight: 0,
  });
  await env.ready();

  assert.equal(image.getAttribute("data-act-comic-candidate"), null);
  assert.equal(env.translateCalls.length, 0);

  image.complete = true;
  image.naturalWidth = 436;
  image.naturalHeight = 654;
  env.lastMutationObserver().trigger([
    { type: "attributes", attributeName: "src", target: image },
  ]);
  await env.flush();

  assert.equal(image.getAttribute("data-act-comic-candidate"), "true");
  const observer = env.lastIntersectionObserver();
  assert.deepEqual(observer.targets, [image]);

  observer.enter(image);
  await env.flush();
  assert.equal(env.translateCalls.length, 1);
  assert.equal(image.getAttribute("data-act-state"), "translated");
});

test("re-running discovery does not duplicate observer registrations or requests", async () => {
  const env = createEnvironment();
  const image = env.addImage();
  await env.ready();

  const observer = env.lastIntersectionObserver();
  assert.deepEqual(observer.targets, [image]);

  // A later mutation that re-adds the same node must not register it twice.
  env.lastMutationObserver().trigger([
    { type: "childList", addedNodes: [image], target: env.document.body },
  ]);
  await env.flush();
  assert.deepEqual(observer.targets, [image]);
  assert.equal(env.translateCalls.length, 0);

  observer.enter(image);
  observer.enter(image);
  await env.flush();
  assert.equal(env.translateCalls.length, 1);
  assert.equal(env.sandbox.ACTTranslationQueue.DEFAULT_MAX_CONCURRENT, 1);
});

test("disabling the translator tears down candidates, cards, and overlays, and re-enabling reuses results", async () => {
  const env = createEnvironment();
  const image = env.addImage();
  await env.ready();

  env.lastIntersectionObserver().enter(image);
  await env.flush();
  assert.equal(env.cards().length, 1);
  assert.equal(env.overlays().length, 1);
  assert.equal(image.getAttribute("data-act-state"), "translated");

  env.changeSetting("enabled", false);
  await env.flush();

  assert.equal(image.getAttribute("data-act-comic-candidate"), null);
  assert.equal(image.getAttribute("data-act-state"), null);
  assert.equal(env.cards().length, 0);
  assert.equal(env.overlays().length, 0);

  // Re-enabling re-discovers the image and restores its stored result instead
  // of retranslating it.
  env.changeSetting("enabled", true);
  await env.flush();
  assert.equal(image.getAttribute("data-act-comic-candidate"), "true");
  assert.equal(env.overlays().length, 1);
  assert.equal(env.overlayRegions().length, 1);
  assert.equal(env.translateCalls.length, 1);
});

function regionPayload(x1, y1, x2, y2, text) {
  return {
    original_text: "こんにちは",
    translated_text: text,
    translation_status: "ok",
    source_language: "ja",
    bbox: { x1, y1, x2, y2 },
  };
}

test("every translated region gets its own overlay element on the image", async () => {
  const env = createEnvironment({
    translate: async () => ({
      payload: {
        api_version: "1",
        source_language: "ja",
        target_language: "en",
        image: { width: 400, height: 600 },
        regions: [
          regionPayload(10, 10, 100, 40, "One"),
          regionPayload(10, 100, 100, 130, "Two"),
          regionPayload(10, 200, 100, 230, "Three"),
        ],
      },
      requestId: "22222222-2222-2222-2222-222222222222",
    }),
  });
  const image = env.addImage({
    naturalWidth: 400,
    naturalHeight: 600,
    renderedWidth: 400,
    renderedHeight: 600,
  });
  await env.ready();

  env.lastIntersectionObserver().enter(image);
  await env.flush();

  assert.equal(env.overlays().length, 1);
  assert.deepEqual(
    env.overlayRegions().map((element) => element.textContent),
    ["One", "Two", "Three"],
  );
  assert.deepEqual(
    env.overlayRegions().map((element) => element.style.left),
    ["10px", "10px", "10px"],
  );
  assert.deepEqual(
    env.overlayRegions().map((element) => element.style.top),
    ["10px", "100px", "200px"],
  );
});

test("Alt+Click does not duplicate an existing overlay", async () => {
  const env = createEnvironment();
  const image = env.addImage();
  await env.ready();

  env.lastIntersectionObserver().enter(image);
  await env.flush();
  assert.equal(env.overlays().length, 1);

  env.altClick(image);
  await env.flush();

  assert.equal(env.translateCalls.length, 1);
  assert.equal(env.overlays().length, 1);
  assert.equal(env.overlayRegions().length, 1);
});

test("a source change removes the stale overlay and allows a fresh translation", async () => {
  const env = createEnvironment();
  const image = env.addImage();
  await env.ready();

  env.lastIntersectionObserver().enter(image);
  await env.flush();
  assert.equal(env.overlays().length, 1);

  // Lazy loading swaps the placeholder for the real asset.
  env.lastMutationObserver().trigger([
    { type: "attributes", attributeName: "src", target: image },
  ]);
  await env.flush();

  assert.equal(env.overlays().length, 0, "the old overlay is not left behind");
  assert.equal(env.cards().length, 0);

  env.lastIntersectionObserver().enter(image);
  await env.flush();

  assert.equal(env.translateCalls.length, 2);
  assert.equal(env.overlays().length, 1);
});

test("removing a translated image removes its overlay and debug card", async () => {
  const env = createEnvironment();
  const image = env.addImage();
  await env.ready();

  env.lastIntersectionObserver().enter(image);
  await env.flush();
  assert.equal(env.overlays().length, 1);
  assert.equal(env.cards().length, 1);

  image.remove();
  env.lastMutationObserver().trigger([
    { type: "childList", addedNodes: [], removedNodes: [image], target: env.document.body },
  ]);
  await env.flush();

  assert.equal(env.overlays().length, 0);
  assert.equal(env.cards().length, 0);
});

function resultWithText(text, { status = "ok" } = {}) {
  return {
    payload: {
      api_version: "1",
      source_language: "ja",
      target_language: "en",
      image: { width: 436, height: 654 },
      regions: [
        {
          original_text: "こんにちは",
          translated_text: text,
          translation_status: status,
          source_language: "ja",
          bbox: { x1: 4, y1: 8, x2: 40, y2: 60 },
        },
      ],
    },
    requestId: "33333333-3333-3333-3333-333333333333",
  };
}

function entryTexts(env) {
  return env
    .feedEntries()
    .map((entry) => entry.querySelector(".act-feed-translated").textContent);
}

test("a successful translation adds one feed entry with its regions", async () => {
  const env = createEnvironment();
  const image = env.addImage();
  await env.ready();

  env.lastIntersectionObserver().enter(image);
  await env.flush();

  assert.equal(env.feedEntries().length, 1);
  const [entry] = env.feedEntries();
  assert.equal(entry.querySelector(".act-feed-entry-title").textContent, "Image 1");
  assert.equal(entry.querySelectorAll(".act-feed-region").length, 1);
  assert.equal(entry.querySelector(".act-feed-translated").textContent, "Hello");
  assert.equal(
    entry.querySelector(".act-feed-entry-langs").textContent,
    "Japanese → English",
  );
  assert.equal(env.feedShell().dataset.actFeedOpen, "false", "collapsed by default");
});

test("the feed keeps page order when a later image is translated first", async () => {
  let calls = 0;
  const env = createEnvironment({
    translate: async () => {
      calls += 1;
      return resultWithText(calls === 1 ? "finished-first" : "finished-second");
    },
  });
  const imageA = env.addImage({ src: "a.png" });
  const imageB = env.addImage({ src: "b.png" });
  await env.ready();
  const observer = env.lastIntersectionObserver();

  // The viewport reaches B first, so B's request finishes first.
  observer.enter(imageB);
  await env.flush();
  observer.enter(imageA);
  await env.flush();

  assert.equal(env.translateCalls.length, 2);
  assert.deepEqual(entryTexts(env), ["finished-second", "finished-first"]);
  assert.equal(env.feedEntries().length, 2);
});

test("opening the feed after translating shows the stored entries", async () => {
  const env = createEnvironment();
  const imageA = env.addImage({ src: "a.png" });
  const imageB = env.addImage({ src: "b.png" });
  await env.ready();
  const observer = env.lastIntersectionObserver();
  observer.enter(imageA);
  await env.flush();
  observer.enter(imageB);
  await env.flush();

  assert.equal(env.feedShell().dataset.actFeedOpen, "false");
  env.clickFeedToggle();

  assert.equal(env.feedShell().dataset.actFeedOpen, "true");
  assert.equal(env.feedEntries().length, 2);
});

test("clicking a feed entry scrolls its image into view without retranslating", async () => {
  const env = createEnvironment();
  const imageA = env.addImage({ src: "a.png" });
  const imageB = env.addImage({ src: "b.png" });
  await env.ready();
  const observer = env.lastIntersectionObserver();
  observer.enter(imageA);
  await env.flush();
  observer.enter(imageB);
  await env.flush();

  env.clickFeedEntry(1);

  assert.equal(env.scrollCalls.length, 1);
  assert.equal(env.scrollCalls[0].image, imageB);
  assert.equal(env.scrollCalls[0].options.behavior, "smooth");
  assert.equal(env.translateCalls.length, 2, "navigation never translates again");
});

test("the active feed entry follows the image crossing the viewport middle", async () => {
  const env = createEnvironment();
  const imageA = env.addImage({ src: "a.png" });
  const imageB = env.addImage({ src: "b.png" });
  await env.ready();
  const observer = env.lastIntersectionObserver();
  observer.enter(imageA);
  await env.flush();
  observer.enter(imageB);
  await env.flush();

  const activity = env.feedActivityObserver();
  assert.ok(activity, "the feed tracks which image is being read");
  activity.enter(imageB);

  const [first, second] = env.feedEntries();
  assert.equal(second.classList.contains("act-feed-entry-active"), true);
  assert.equal(first.classList.contains("act-feed-entry-active"), false);

  activity.enter(imageA);
  assert.equal(first.classList.contains("act-feed-entry-active"), true);
  assert.equal(second.classList.contains("act-feed-entry-active"), false);
});

test("changing the source language invalidates overlays, feed entries, and results", async () => {
  const env = createEnvironment();
  const image = env.addImage();
  await env.ready();
  env.lastIntersectionObserver().enter(image);
  await env.flush();

  assert.equal(env.overlays().length, 1);
  assert.equal(env.feedEntries().length, 1);

  env.changeSetting("sourceLanguage", "ko");
  await env.flush();

  assert.equal(env.overlays().length, 0, "stale overlay removed");
  assert.equal(env.feedEntries().length, 0, "stale feed entry removed");
  assert.equal(env.cards().length, 0);
  assert.equal(image.getAttribute("data-act-state"), null);

  // The image is eligible again under the new language identity.
  env.lastIntersectionObserver().enter(image);
  await env.flush();
  assert.equal(env.translateCalls.length, 2);
  assert.equal(env.translateCalls[1].sourceLanguage, "ko");
  assert.equal(env.feedEntries().length, 1);
});

test("a source change removes the stale feed entry", async () => {
  const env = createEnvironment();
  const image = env.addImage();
  await env.ready();
  env.lastIntersectionObserver().enter(image);
  await env.flush();
  assert.equal(env.feedEntries().length, 1);

  env.lastMutationObserver().trigger([
    { type: "attributes", attributeName: "src", target: image },
  ]);
  await env.flush();

  assert.equal(env.feedEntries().length, 0);
  assert.equal(env.overlays().length, 0);
});

test("removing a translated image removes its feed entry", async () => {
  const env = createEnvironment();
  const image = env.addImage();
  await env.ready();
  env.lastIntersectionObserver().enter(image);
  await env.flush();
  assert.equal(env.feedEntries().length, 1);

  image.remove();
  env.lastMutationObserver().trigger([
    {
      type: "childList",
      addedNodes: [],
      removedNodes: [image],
      target: env.document.body,
    },
  ]);
  await env.flush();

  assert.equal(env.feedEntries().length, 0);
});

test("disabling the translator removes the feed panel", async () => {
  const env = createEnvironment();
  const image = env.addImage();
  await env.ready();
  env.lastIntersectionObserver().enter(image);
  await env.flush();
  assert.ok(env.feedShell());

  env.changeSetting("enabled", false);
  await env.flush();

  assert.equal(env.feedShell(), null, "no feed panel while disabled");
  assert.equal(env.feedToggle(), null);
  assert.equal(env.overlays().length, 0);
});

test("re-enabling restores overlays and feed entries from stored results", async () => {
  const env = createEnvironment();
  const image = env.addImage();
  await env.ready();
  env.lastIntersectionObserver().enter(image);
  await env.flush();
  assert.equal(env.translateCalls.length, 1);

  env.changeSetting("enabled", false);
  await env.flush();
  env.changeSetting("enabled", true);
  await env.flush();

  assert.equal(env.translateCalls.length, 1, "no retranslation on re-enable");
  assert.equal(env.overlays().length, 1);
  assert.equal(env.feedEntries().length, 1);
});

test("the overlay toggle hides overlays and restores them without retranslating", async () => {
  const env = createEnvironment();
  const image = env.addImage();
  await env.ready();

  env.changeSetting("showOverlays", false);
  await env.flush();

  env.lastIntersectionObserver().enter(image);
  await env.flush();

  assert.equal(env.translateCalls.length, 1);
  assert.equal(env.overlays().length, 0, "translations still happen, nothing is drawn");

  env.changeSetting("showOverlays", true);
  await env.flush();

  assert.equal(env.translateCalls.length, 1);
  assert.equal(env.overlays().length, 1, "the stored result is re-rendered");
  assert.equal(env.overlayRegions().length, 1);
});
