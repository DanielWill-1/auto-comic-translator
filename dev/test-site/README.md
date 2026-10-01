# Chapter test fixture (Phase 3.4 / 3.5 / 3.6)

A local, comic-like page used to check the lazy queue, the on-image overlay, and
the translation feed in a real browser. Every image is referenced from this
repository's `datas/` directory (or a small local asset) — nothing is downloaded
and nothing is invented.

Serve the repository root and open the fixture:

```bash
python -m http.server 8080 --bind 127.0.0.1
# http://127.0.0.1:8080/dev/test-site/
```

Start the backend first (`uvicorn backend.main:app --host 127.0.0.1 --port 8000`)
and load the unpacked `extension/` directory in Chromium.

## Detection rules the fixture is built around

`extension/lib/image-detector.js` marks an image as a candidate only when it is
connected, visible, at least `300 × 300` natural pixels, at least `150000` pixels
in area, at least 1 px in both rendered dimensions, and not an SVG or a tiny
tracking-style asset. Labels are `figcaption` elements placed outside the image,
so the reader's own content is never mistaken for page furniture.

## Inventory

Candidates (expected to be outlined and translated):

| Section | Image | Natural size | Notes |
| --- | --- | --- | --- |
| Japanese 1 | `japanes/…122747.png` | 434 × 640 | portrait page |
| Japanese 2 | `japanes/…122754.png` | 440 × 622 | portrait page |
| Japanese 3 | `japanes/…122757.png` | 423 × 657 | portrait page (also the narrow case) |
| Japanese 4 | `japanes/…122805.png` | 436 × 654 | portrait page (also the duplicate pair) |
| Chinese 1 | `chinese/…015218.png` | 1123 × 358 | wide landscape strip |
| Chinese 2 | `chinese/…015428.png` | 773 × 356 | landscape crop |
| Chinese 3 | `chinese/…015443.png` | 829 × 472 | landscape panel |
| Korean 1 | `korean/…015554.png` | 555 × 588 | near-square sound-effect panel, no text expected |
| Korean 2 | `korean/…015601.png` | 451 × 335 | landscape panel |
| Duplicate A/B | `japanes/…122805.png` ×2 | 436 × 654 | same source rendered twice, two entries |
| Responsive | `japanes/…122810.png` | 450 × 656 | `width: 100%`, `max-width: 520px` |
| Narrow | `japanes/…122757.png` | 423 × 657 | rendered 180 px wide to force wrapping |

That is 13 candidate `<img>` elements on load, all real repository files.

Rejections (expected to stay unmarked):

| Case | Image | Why it is rejected |
| --- | --- | --- |
| SVG icon | `assets/tiny-icon.svg` | SVG source, no raster dimensions |
| SVG avatar | `assets/avatar.svg` | SVG source |
| SVG banner | `assets/banner.svg` | SVG source, and only 120 px tall |
| Hidden image | `japanes/…122805.png` in `.hidden-card` | `display: none` |
| Broken image | `assets/missing-comic-page.png` | intentionally missing file |
| Tiny raster | `assets/tiny-panel.png` | 32 × 24, below both thresholds |
| Japanese crops | `…122412.png`, `…122415.png`, `…122417.png` | real manga crops below the 300 px height |
| Chinese crops | `…015435.png` (663 × 297), `…015438.png` (710 × 287) | below the 300 px height |
| Korean crops | `…015537.png` (486 × 297), `…015541.png` (415 × 169) | below the 300 px height |
| Lazy placeholder | `assets/placeholder.svg` | SVG placeholder until replaced |

The below-threshold entries are real comic crops from `datas/`, kept so the
detector's size rules are exercised by genuine material rather than only by
icons.

## Controls

| Control | Effect |
| --- | --- |
| **Add dynamic comic image** | Appends a real Japanese, Chinese, or Korean page (cycling) to `#dynamic-reader` |
| **Remove dynamic image** | Removes the most recently added panel |
| **Load real image** | Replaces the SVG placeholder in `#lazy-comic-image` with a real Chinese page |
| **Toggle responsive width** | Switches the responsive card between `max-width: 520px` and `300px` to force a resize |

## Phase 3.4 checks (lazy queue)

1. Load the page with the backend running and the popup's source language set to
   **Japanese**. Only the images near the viewport should be outlined, and at most
   one request should be in flight.
2. Scroll slowly through the Japanese section. Each image should be outlined,
   translated once, and keep its overlay while scrolling back up.
3. Scroll back and forth across a translated image: it must not be translated a
   second time (no repeat entries in the backend log).
4. Alt+Click an image that is already translated: the stored result is shown
   again and no new request is sent.
5. Alt+Click an image that failed: exactly one new request is sent.
6. Press **Add dynamic comic image** and scroll to it: the new image is
   discovered and translated. Press **Remove dynamic image**: no error appears.
7. Press **Load real image**, then scroll to it: the replaced source is
   discovered and translated.

## Phase 3.5 checks (overlay)

1. Each translated image shows the translated text inside the region rectangles
   of the original image, with no layout shift (the page must not reflow).
2. Press **Toggle responsive width** with an overlay visible: the overlay follows
   the image immediately (ResizeObserver) and the text stays inside its region.
3. Scroll a translated image partly out of view: overlays scroll with the page and
   stay aligned.
4. Toggle **Show translations on image** off and on in the popup: overlays
   disappear and come back without new requests.
5. Alt+Click one image: the development card expands with region details; the
   automatically translated images keep theirs collapsed.

## Phase 3.6 checks (translation feed)

1. Translate two or three images, then press the **Feed** button (bottom-right).
   Every translated image should be listed with its index, language pair, region
   summary, and each region's original and translated text.
2. Confirm the entries are in page order even if you translated a lower image
   first (scroll to image 3 before image 1).
3. Confirm the feed panel does not change the page layout (no reflow, and the
   comic reader keeps its own scroll position).
4. Click an entry header: the browser scrolls that image into view smoothly and
   **no new request** is sent.
5. Scroll the page: the entry for the image crossing the middle of the viewport
   is highlighted, and only that one.
6. Check the Korean near-square panel (no text expected): it should produce an
   empty result rather than an error, and no feed entry with invented text.
7. Alt+Click an image whose request failed: the compact "Translation unavailable"
   entry is replaced in place by the successful result.
8. Switch the popup's source language to **Korean** (or another language): every
   overlay and feed entry disappears, and scrolling back re-translates the images
   under the new language.
9. Disable the translator from the popup: overlays and the feed panel both
   disappear. Re-enable it: they come back without new requests.
10. Confirm the feed never shows request IDs, timings, or bounding boxes.

## Known limits of this fixture

- All Japanese samples are portrait pages of similar size; the wide/landscape
  variety comes from the Chinese and Korean crops.
- Only Korean and Japanese have enough full-size samples for a full section;
  Chinese has three candidates in `datas/`.
- The Korean near-square panel contains no real text, so it is the fixture's
  zero-region case, not a translation case.
- A full scroll translates 13 images and takes several minutes on CPU-only
  inference. Test section by section.
- With **Auto** selected, the readers that share one model set now run once, and
  the source language is resolved from the script of the recognized text rather
  than from the reader that happened to produce it. Han-only pages resolve to
  `zh` (Simplified); select `zh-Hant` explicitly for Traditional Chinese. Auto is
  still slower than an explicit language — prefer one when the page's language is
  known.
