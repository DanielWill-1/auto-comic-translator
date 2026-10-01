"use strict";

/*
 * Phase 3.5 — overlay renderer tests.
 *
 * Covers coordinate mapping, non-uniform scaling, object-fit handling, bounds
 * validation, one-element-per-region rendering, deduplication, resize
 * repositioning, cleanup, and safe text insertion. No browser is required.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

const { createOverlayEnvironment } = require("./harness.js");

function region(x1, y1, x2, y2, text = "Hello", status = "ok") {
  return {
    original_text: "こんにちは",
    translated_text: text,
    translation_status: status,
    source_language: "ja",
    bbox: { x1, y1, x2, y2 },
  };
}

function payload(regions, { width = 1000, height = 2000 } = {}) {
  return {
    api_version: "1",
    source_language: "ja",
    target_language: "en",
    image: { width, height },
    regions,
  };
}

test("a backend bbox maps onto the displayed image size", () => {
  const env = createOverlayEnvironment();
  const drawnRect = { left: 0, top: 0, width: 500, height: 1000 };

  const rect = env.api.mapRegionRect(region(100, 200, 300, 400), {
    drawnRect,
    clipRect: drawnRect,
    imageWidth: 1000,
    imageHeight: 2000,
  });

  assert.deepEqual({ ...rect }, { left: 50, top: 100, width: 100, height: 100 });
});

test("non-uniform scaling is supported", () => {
  const env = createOverlayEnvironment();
  const drawnRect = { left: 0, top: 0, width: 500, height: 500 };

  const rect = env.api.mapRegionRect(region(100, 200, 300, 400), {
    drawnRect,
    clipRect: drawnRect,
    imageWidth: 1000,
    imageHeight: 2000,
  });

  assert.deepEqual({ ...rect }, { left: 50, top: 50, width: 100, height: 50 });
});

test("invalid or out-of-range regions fail safely", () => {
  const env = createOverlayEnvironment();
  const drawnRect = { left: 0, top: 0, width: 500, height: 1000 };
  const geometry = {
    drawnRect,
    clipRect: drawnRect,
    imageWidth: 1000,
    imageHeight: 2000,
  };

  const invalid = [
    region(-10, 200, 300, 400), // negative
    region(100, 200, 1200, 400), // beyond the source width
    region(100, 200, 300, 2400), // beyond the source height
    region(100, 200, 100, 400), // zero width
    region(100, 200, 300, 200), // zero height
    region(Number.NaN, 200, 300, 400),
    region(100, 200, Infinity, 400),
    { translated_text: "no bbox", translation_status: "ok" },
    { translated_text: "bad bbox", bbox: "nope", translation_status: "ok" },
    null,
  ];

  for (const candidate of invalid) {
    assert.equal(env.api.mapRegionRect(candidate, geometry), null);
  }
});

test("object-fit contain maps the letterboxed bitmap", () => {
  const env = createOverlayEnvironment();

  const drawn = env.api.computeDrawnRect({
    elementLeft: 0,
    elementTop: 0,
    elementWidth: 500,
    elementHeight: 500,
    naturalWidth: 1000,
    naturalHeight: 2000,
    objectFit: "contain",
  });

  assert.deepEqual({ ...drawn }, { left: 125, top: 0, width: 250, height: 500 });
});

test("object-fit cover clips regions to the visible part of the image", () => {
  const env = createOverlayEnvironment();
  const drawn = env.api.computeDrawnRect({
    elementLeft: 0,
    elementTop: 0,
    elementWidth: 500,
    elementHeight: 500,
    naturalWidth: 1000,
    naturalHeight: 2000,
    objectFit: "cover",
  });
  assert.deepEqual({ ...drawn }, { left: 0, top: -250, width: 500, height: 1000 });

  const geometry = {
    drawnRect: drawn,
    clipRect: { left: 0, top: 0, width: 500, height: 500 },
    imageWidth: 1000,
    imageHeight: 2000,
  };

  // Partially visible: the top of the region is cropped by the element box.
  assert.deepEqual(
    { ...env.api.mapRegionRect(region(0, 400, 500, 700), geometry) },
    { left: 0, top: 0, width: 250, height: 100 },
  );
  // Fully cropped away: skipped rather than placed outside the image.
  assert.equal(env.api.mapRegionRect(region(0, 100, 500, 300), geometry), null);
});

test("one response with three regions renders exactly three elements", () => {
  const env = createOverlayEnvironment();
  const image = env.addImage();

  const count = env.renderer.render(
    image,
    payload([
      region(100, 200, 300, 400, "One"),
      region(100, 600, 300, 800, "Two"),
      region(100, 1000, 300, 1200, "Three"),
    ]),
  );

  assert.equal(count, 3);
  assert.equal(env.layers().length, 1);
  const regions = env.regions();
  assert.equal(regions.length, 3);
  assert.deepEqual(
    regions.map((element) => element.textContent),
    ["One", "Two", "Three"],
  );
  assert.deepEqual(
    regions.map((element) => element.style.left),
    ["50px", "50px", "50px"],
  );
  assert.deepEqual(
    regions.map((element) => element.style.top),
    ["100px", "300px", "500px"],
  );
});

test("repeated renders do not duplicate the layer or its regions", () => {
  const env = createOverlayEnvironment();
  const image = env.addImage();
  const result = payload([
    region(100, 200, 300, 400),
    region(100, 600, 300, 800),
    region(100, 1000, 300, 1200),
  ]);

  env.renderer.render(image, result);
  env.renderer.render(image, result);
  env.renderer.render(image, result);

  assert.equal(env.layers().length, 1);
  assert.equal(env.regions().length, 3);
  assert.equal(env.renderer.overlayCount(), 1);
});

test("a resized image is repositioned without a new translation", () => {
  const env = createOverlayEnvironment();
  const image = env.addImage();
  env.renderer.render(image, payload([region(100, 200, 300, 400)]));

  const [observer] = env.resizeObservers();
  assert.deepEqual(observer.targets, [image]);
  assert.equal(env.regions()[0].style.left, "50px");

  image.rect = { width: 250, height: 500, top: 0, left: 0, right: 250, bottom: 500 };
  image.clientWidth = 250;
  image.clientHeight = 500;
  observer.trigger();

  assert.equal(env.regions()[0].style.left, "25px");
  assert.equal(env.regions()[0].style.top, "50px");
  assert.equal(env.regions()[0].style.width, "50px");
  assert.equal(env.layers().length, 1);
});

test("removing an image removes its overlay and resize observation", () => {
  const env = createOverlayEnvironment();
  const image = env.addImage();
  env.renderer.render(image, payload([region(100, 200, 300, 400)]));
  assert.equal(env.layers().length, 1);

  image.remove();
  assert.equal(env.renderer.remove(image), true);

  assert.equal(env.layers().length, 0);
  assert.equal(env.renderer.overlayCount(), 0);
  assert.deepEqual(env.resizeObservers()[0].targets, []);
  assert.equal(env.renderer.remove(image), false);
});

test("removeAll clears every overlay layer", () => {
  const env = createOverlayEnvironment();
  const first = env.addImage();
  const second = env.addImage();
  env.renderer.render(first, payload([region(100, 200, 300, 400)]));
  env.renderer.render(second, payload([region(100, 200, 300, 400)]));
  assert.equal(env.layers().length, 2);

  env.renderer.removeAll();

  assert.equal(env.layers().length, 0);
  assert.equal(env.renderer.overlayCount(), 0);
});

test("a source change drops the old overlay and a new result renders fresh", () => {
  const env = createOverlayEnvironment();
  const image = env.addImage();
  env.renderer.render(image, payload([region(100, 200, 300, 400, "Old text")]));
  assert.equal(env.regions()[0].textContent, "Old text");

  // content.js calls remove() when the image's source changes.
  env.renderer.remove(image);
  assert.equal(env.layers().length, 0);

  env.renderer.render(image, payload([region(500, 900, 700, 1100, "New text")]));
  assert.equal(env.layers().length, 1);
  assert.deepEqual(
    env.regions().map((element) => element.textContent),
    ["New text"],
  );
  assert.equal(env.regions()[0].style.left, "250px");
});

test("fallback and empty regions are not drawn over the image", () => {
  const env = createOverlayEnvironment();
  const image = env.addImage();

  const count = env.renderer.render(
    image,
    payload([
      region(100, 200, 300, 400, "Translated"),
      region(100, 600, 300, 800, "こんにちは", "fallback"),
      region(100, 1000, 300, 1200, "   "),
    ]),
  );

  assert.equal(count, 1);
  assert.deepEqual(
    env.regions().map((element) => element.textContent),
    ["Translated"],
  );
});

test("translated text is inserted as text, never as markup", () => {
  const env = createOverlayEnvironment();
  const image = env.addImage();
  const hostile = '<img src=x onerror=alert(1)><script>alert(2)</script>';

  env.renderer.render(image, payload([region(100, 200, 300, 400, hostile)]));

  const [element] = env.regions();
  assert.equal(element.textContent, hostile);
  assert.equal(element.childNodes.length, 0);
  assert.equal(element.querySelectorAll("img").length, 0);
  assert.equal(element.querySelectorAll("script").length, 0);
});

test("font size is derived from the region height and clamped", () => {
  const env = createOverlayEnvironment();

  assert.equal(env.api.fontSizeForRect({ height: 20 }), env.api.MIN_FONT_PX);
  assert.equal(env.api.fontSizeForRect({ height: 30 }), 15);
  assert.equal(env.api.fontSizeForRect({ height: 600 }), env.api.MAX_FONT_PX);
});

test("regions are positioned relative to the layer's containing block", () => {
  const env = createOverlayEnvironment();
  const container = new (require("./harness.js").FakeElement)(
    "div",
    env.document,
  );
  container.style.position = "relative";
  container.rect = { width: 600, height: 1200, top: 40, left: 25, right: 625, bottom: 1240 };
  container.clientLeft = 0;
  container.clientTop = 0;
  container.scrollLeft = 0;
  container.scrollTop = 0;
  env.document.body.append(container);

  const image = env.addImage({ parent: container, left: 25, top: 40 });
  env.renderer.render(image, payload([region(100, 200, 300, 400)]));

  const [element] = env.regions();
  assert.equal(element.style.left, "50px");
  assert.equal(element.style.top, "100px");
});

test("a detached image is not rendered", () => {
  const env = createOverlayEnvironment();
  const image = env.addImage({ connected: false });

  assert.equal(env.renderer.render(image, payload([region(100, 200, 300, 400)])), 0);
  assert.equal(env.layers().length, 0);
});
