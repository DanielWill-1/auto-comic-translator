/*
 * Phase 3.5 — translated-region overlay renderer.
 *
 * Renders the translated OCR regions of a validated API v1 response over the
 * original comic image as absolutely positioned DOM nodes. The bitmap itself is
 * never modified: no canvas, no inpainting, no replacement.
 *
 * Coordinate contract: API `bbox` values are in ORIGINAL image pixels and are
 * scaled against the rectangle where the browser actually draws the bitmap.
 * That rectangle accounts for the element's content box and for `object-fit`
 * (`fill`, `contain`, `cover`, `none`, `scale-down`).
 *
 * The overlay layer is inserted as a sibling immediately after the image and is
 * absolutely positioned in the same containing block, so normal page scrolling
 * moves the image and its overlay together without per-scroll measurement.
 *
 * The module is DOM-injectable and split into pure geometry helpers plus a
 * renderer factory so it can be tested without a browser.
 */
(() => {
  const MIN_FONT_PX = 11;
  const MAX_FONT_PX = 22;
  const FONT_HEIGHT_RATIO = 0.5;
  const LAYER_Z_INDEX = 2147483000;
  const OBJECT_FIT_VALUES = new Set([
    "fill",
    "contain",
    "cover",
    "none",
    "scale-down",
  ]);

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  /*
   * Rectangle where the browser draws the bitmap, in viewport coordinates.
   * `elementWidth`/`elementHeight` are the image's content box (border box
   * minus borders), because padding/borders are not part of the drawn image.
   */
  function computeDrawnRect({
    elementLeft,
    elementTop,
    elementWidth,
    elementHeight,
    naturalWidth,
    naturalHeight,
    objectFit = "fill",
  }) {
    const fit = OBJECT_FIT_VALUES.has(objectFit) ? objectFit : "fill";
    const hasNaturalSize = naturalWidth > 0 && naturalHeight > 0;
    if (!hasNaturalSize || fit === "fill") {
      return {
        left: elementLeft,
        top: elementTop,
        width: elementWidth,
        height: elementHeight,
      };
    }

    const widthScale = elementWidth / naturalWidth;
    const heightScale = elementHeight / naturalHeight;
    let width;
    let height;
    if (fit === "contain") {
      const scale = Math.min(widthScale, heightScale);
      width = naturalWidth * scale;
      height = naturalHeight * scale;
    } else if (fit === "cover") {
      const scale = Math.max(widthScale, heightScale);
      width = naturalWidth * scale;
      height = naturalHeight * scale;
    } else if (fit === "none") {
      width = naturalWidth;
      height = naturalHeight;
    } else {
      const scale = Math.min(1, Math.min(widthScale, heightScale));
      width = naturalWidth * scale;
      height = naturalHeight * scale;
    }

    return {
      left: elementLeft + (elementWidth - width) / 2,
      top: elementTop + (elementHeight - height) / 2,
      width,
      height,
    };
  }

  /*
   * Map one backend region onto the drawn bitmap. Returns `null` for a region
   * that cannot be placed safely (malformed, out of range, zero-size, or fully
   * outside the visible part of the image). Coordinates are relative to the
   * overlay layer's containing block.
   */
  function mapRegionRect(region, { drawnRect, clipRect, imageWidth, imageHeight }) {
    const bbox = region?.bbox;
    if (!bbox || typeof bbox !== "object") {
      return null;
    }
    const coordinates = [bbox.x1, bbox.y1, bbox.x2, bbox.y2];
    if (coordinates.some((value) => !Number.isFinite(value))) {
      return null;
    }
    if (bbox.x1 < 0 || bbox.y1 < 0 || bbox.x2 <= bbox.x1 || bbox.y2 <= bbox.y1) {
      return null;
    }
    if (bbox.x2 > imageWidth || bbox.y2 > imageHeight) {
      return null;
    }

    const scaleX = drawnRect.width / imageWidth;
    const scaleY = drawnRect.height / imageHeight;
    let left = drawnRect.left + bbox.x1 * scaleX;
    let top = drawnRect.top + bbox.y1 * scaleY;
    let right = drawnRect.left + bbox.x2 * scaleX;
    let bottom = drawnRect.top + bbox.y2 * scaleY;

    // `object-fit: cover`/`none` crop the bitmap inside the element box; the
    // visible part is the intersection with the element's content box.
    const clip = clipRect || drawnRect;
    left = Math.max(left, clip.left);
    top = Math.max(top, clip.top);
    right = Math.min(right, clip.left + clip.width);
    bottom = Math.min(bottom, clip.top + clip.height);
    if (right - left < 1 || bottom - top < 1) {
      return null;
    }

    return { left, top, width: right - left, height: bottom - top };
  }

  function fontSizeForRect(rect) {
    return clamp(
      Math.round(rect.height * FONT_HEIGHT_RATIO),
      MIN_FONT_PX,
      MAX_FONT_PX,
    );
  }

  function createOverlayRenderer({
    document: doc = globalThis.document,
    resizeObserverFactory = globalThis.ResizeObserver,
    styleOf = (element) => globalThis.getComputedStyle(element),
    onEvent = () => {},
  } = {}) {
    if (!doc) {
      throw new TypeError("A document is required to render overlays.");
    }

    const records = new Map();
    let resizeObserver = null;

    function layerOrigin(layer) {
      const view = doc.defaultView || globalThis;
      const scrollX = view.scrollX || 0;
      const scrollY = view.scrollY || 0;
      const parent = layer.offsetParent;
      if (
        !parent ||
        parent === doc.body ||
        parent === doc.documentElement
      ) {
        // Absolutely positioned in the initial containing block: document
        // coordinates are viewport coordinates plus the scroll offset.
        return { left: -scrollX, top: -scrollY };
      }
      const rect = parent.getBoundingClientRect();
      return {
        left: rect.left + (parent.clientLeft || 0) - (parent.scrollLeft || 0),
        top: rect.top + (parent.clientTop || 0) - (parent.scrollTop || 0),
      };
    }

    function measure(image, record, payload) {
      const elementRect = image.getBoundingClientRect();
      const style = styleOf(image) || {};
      const contentLeft = elementRect.left + (image.clientLeft || 0);
      const contentTop = elementRect.top + (image.clientTop || 0);
      const contentWidth = image.clientWidth || elementRect.width;
      const contentHeight = image.clientHeight || elementRect.height;
      const drawnRect = computeDrawnRect({
        elementLeft: contentLeft,
        elementTop: contentTop,
        elementWidth: contentWidth,
        elementHeight: contentHeight,
        naturalWidth: image.naturalWidth || payload.image.width,
        naturalHeight: image.naturalHeight || payload.image.height,
        objectFit: style.objectFit || "fill",
      });
      const origin = layerOrigin(record.layer);
      return {
        drawnRect: {
          left: drawnRect.left - origin.left,
          top: drawnRect.top - origin.top,
          width: drawnRect.width,
          height: drawnRect.height,
        },
        clipRect: {
          left: contentLeft - origin.left,
          top: contentTop - origin.top,
          width: contentWidth,
          height: contentHeight,
        },
        imageWidth: payload.image.width,
        imageHeight: payload.image.height,
      };
    }

    function createRegionElement(region, rect) {
      const element = doc.createElement("div");
      element.className = "act-translation-region";
      element.dataset.actTranslationRegion = "true";
      element.style.left = `${rect.left}px`;
      element.style.top = `${rect.top}px`;
      element.style.width = `${rect.width}px`;
      element.style.minHeight = `${rect.height}px`;
      element.style.fontSize = `${fontSizeForRect(rect)}px`;
      // Translated text is always inserted as text, never as markup.
      element.textContent =
        typeof region.translated_text === "string" ? region.translated_text : "";
      return element;
    }

    function ensureRecord(image) {
      let record = records.get(image);
      if (record?.layer.isConnected) {
        return record;
      }
      if (record) {
        records.delete(image);
      }

      const layer = doc.createElement("div");
      layer.className = "act-overlay-layer";
      layer.dataset.actOverlayLayer = "true";
      layer.setAttribute("aria-hidden", "true");
      layer.style.zIndex = String(LAYER_Z_INDEX);
      image.insertAdjacentElement("afterend", layer);

      record = { layer, payload: null, regionCount: 0 };
      records.set(image, record);

      if (typeof resizeObserverFactory === "function") {
        if (!resizeObserver) {
          resizeObserver = new resizeObserverFactory(handleResize);
        }
        resizeObserver.observe(image);
      }
      return record;
    }

    function draw(image, record) {
      const payload = record.payload;
      if (!payload) {
        return 0;
      }
      const geometry = measure(image, record, payload);
      const elements = [];
      for (const region of payload.regions || []) {
        // A fallback region carries the untranslated original text; drawing it
        // over its own source text would not help a reader, so it is skipped.
        if (region?.translation_status === "fallback") {
          continue;
        }
        if (
          typeof region?.translated_text !== "string" ||
          region.translated_text.trim() === ""
        ) {
          continue;
        }
        const rect = mapRegionRect(region, geometry);
        if (!rect) {
          continue;
        }
        elements.push(createRegionElement(region, rect));
      }

      record.layer.replaceChildren(...elements);
      record.regionCount = elements.length;
      return elements.length;
    }

    function handleResize(entries) {
      for (const entry of entries) {
        const image = entry?.target;
        const record = image ? records.get(image) : null;
        if (!record) {
          continue;
        }
        // Resizing only repositions existing regions; no retranslation.
        draw(image, record);
      }
    }

    function render(image, payload) {
      if (!image?.isConnected || !payload?.image) {
        return 0;
      }
      const record = ensureRecord(image);
      record.payload = payload;
      const count = draw(image, record);
      onEvent("rendered", { image, regionCount: count });
      return count;
    }

    function remove(image) {
      const record = records.get(image);
      if (!record) {
        return false;
      }
      record.layer.remove();
      records.delete(image);
      resizeObserver?.unobserve?.(image);
      onEvent("removed", { image });
      return true;
    }

    function removeAll() {
      for (const image of [...records.keys()]) {
        remove(image);
      }
    }

    function cleanup() {
      removeAll();
      resizeObserver?.disconnect?.();
      resizeObserver = null;
    }

    return Object.freeze({
      render,
      remove,
      removeAll,
      cleanup,
      hasOverlay: (image) => records.has(image),
      overlayCount: () => records.size,
      regionCount: (image) => records.get(image)?.regionCount ?? 0,
      layerFor: (image) => records.get(image)?.layer ?? null,
    });
  }

  globalThis.ACTOverlayRenderer = Object.freeze({
    MIN_FONT_PX,
    MAX_FONT_PX,
    LAYER_Z_INDEX,
    computeDrawnRect,
    mapRegionRect,
    fontSizeForRect,
    createOverlayRenderer,
  });
})();
