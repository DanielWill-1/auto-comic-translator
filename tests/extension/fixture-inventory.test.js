"use strict";

/*
 * Phase 3.6 — fixture inventory checks for dev/test-site/.
 *
 * These assertions are static: they verify the fixture page references real
 * repository files, keeps the required negative cases, and contains the
 * expected number of candidate comic images. No OCR or translation models are
 * involved, and no backend is contacted.
 */

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.join(__dirname, "..", "..");
const SITE_DIR = path.join(ROOT, "dev", "test-site");
const HTML = fs.readFileSync(path.join(SITE_DIR, "index.html"), "utf8");

function imageSources(html) {
  const sources = [];
  const pattern = /<img\b[^>]*\bsrc="([^"]+)"/g;
  let match = pattern.exec(html);
  while (match) {
    sources.push(match[1]);
    match = pattern.exec(html);
  }
  return sources;
}

function resolvesInRepository(src) {
  const decoded = decodeURIComponent(src);
  const absolute = path.resolve(SITE_DIR, decoded);
  return absolute.startsWith(ROOT) && fs.existsSync(absolute);
}

const SOURCES = imageSources(HTML);

test("every non-intentional fixture image points at a real repository file", () => {
  const intentional = ["assets/missing-comic-page.png"];
  for (const src of SOURCES) {
    if (intentional.includes(src)) {
      continue;
    }
    assert.ok(resolvesInRepository(src), `fixture references a missing file: ${src}`);
  }
});

test("the intentionally broken image source does not exist", () => {
  assert.ok(SOURCES.includes("assets/missing-comic-page.png"));
  assert.equal(
    resolvesInRepository("assets/missing-comic-page.png"),
    false,
    "the broken-image fixture must stay broken",
  );
});

test("the fixture keeps every required negative case", () => {
  for (const asset of [
    "assets/tiny-icon.svg",
    "assets/avatar.svg",
    "assets/banner.svg",
    "assets/tiny-panel.png",
    "assets/placeholder.svg",
  ]) {
    assert.ok(SOURCES.includes(asset), `missing negative fixture ${asset}`);
    assert.ok(resolvesInRepository(asset), `${asset} does not exist`);
  }

  // Hidden image and below-threshold real crops stay in the page.
  assert.ok(HTML.includes('class="hidden-image"'));
  assert.ok(HTML.includes("below minimum height"));
});

test("the fixture keeps the required development controls", () => {
  for (const control of [
    "add-comic-image",
    "remove-comic-image",
    "load-lazy-image",
    "toggle-responsive",
  ]) {
    assert.ok(HTML.includes(`id="${control}"`), `missing control ${control}`);
  }
  const site = fs.readFileSync(path.join(SITE_DIR, "site.js"), "utf8");
  assert.ok(site.includes("dynamicSamples"));
  assert.ok(site.includes("lazySource"));
});

test("the chapter sections carry the expected candidate comic images", () => {
  // Candidate = at least 300x300 natural with a 150k+ pixel area, which is what
  // extension/lib/image-detector.js enforces.
  const chapters = {
    japanese: [
      "Screenshot%202026-06-29%20122747.png",
      "Screenshot%202026-06-29%20122754.png",
      "Screenshot%202026-06-29%20122757.png",
      "Screenshot%202026-06-29%20122805.png",
    ],
    chinese: [
      "Screenshot%202026-09-26%20015218.png",
      "Screenshot%202026-09-26%20015428.png",
      "Screenshot%202026-09-26%20015443.png",
    ],
    korean: [
      "Screenshot%202026-09-26%20015554.png",
      "Screenshot%202026-09-26%20015601.png",
    ],
  };
  for (const [section, files] of Object.entries(chapters)) {
    for (const file of files) {
      assert.ok(
        SOURCES.some((src) => src.endsWith(file)),
        `${section} section is missing ${file}`,
      );
      assert.ok(
        SOURCES.filter((src) => src.endsWith(file)).every((src) => resolvesInRepository(src)),
        `${file} is referenced but not present in the repository`,
      );
    }
  }

  const candidateSources = new Set(
    SOURCES.filter((src) => src.includes("/datas/")),
  );
  // 9 chapter candidates + duplicate pair + responsive + narrow.
  assert.ok(
    candidateSources.size >= 10,
    `expected at least 10 distinct comic sources, found ${candidateSources.size}`,
  );
});

test("stress cases are present: duplicate, responsive, narrow, lazy, broken, tiny", () => {
  const duplicate = SOURCES.filter((src) => src.endsWith("122805.png"));
  assert.ok(
    duplicate.length >= 2,
    "the duplicate-source case must render the same image twice",
  );
  assert.ok(HTML.includes("responsive-image"));
  assert.ok(HTML.includes("narrow-image"));
  assert.ok(HTML.includes('id="lazy-comic-image"'));
  assert.ok(HTML.includes("missing-comic-page.png"));
  assert.ok(HTML.includes("tiny-panel.png"));

  const css = fs.readFileSync(path.join(SITE_DIR, "styles.css"), "utf8");
  assert.ok(css.includes(".responsive-image"));
  assert.ok(css.includes(".narrow-image"));
});
