(() => {
  const MIN_NATURAL_WIDTH = 300;
  const MIN_NATURAL_HEIGHT = 300;
  const MIN_NATURAL_AREA = 150_000;
  const MIN_RENDERED_SIZE = 1;

  function reject(reason) {
    return { candidate: false, reason };
  }

  function classifyImage(metrics) {
    if (!metrics || typeof metrics !== "object") {
      return reject("missing image measurements");
    }

    const {
      naturalWidth,
      naturalHeight,
      renderedWidth,
      renderedHeight,
      visible,
    } = metrics;
    const dimensions = [naturalWidth, naturalHeight];
    if (
      dimensions.some((value) => !Number.isFinite(value) || value <= 0)
    ) {
      return reject("natural dimensions unavailable");
    }

    if (
      visible !== true ||
      !Number.isFinite(renderedWidth) ||
      !Number.isFinite(renderedHeight) ||
      renderedWidth <= MIN_RENDERED_SIZE ||
      renderedHeight <= MIN_RENDERED_SIZE
    ) {
      return reject("image is not visibly rendered");
    }

    const naturalArea = naturalWidth * naturalHeight;
    if (
      naturalWidth < MIN_NATURAL_WIDTH ||
      naturalHeight < MIN_NATURAL_HEIGHT ||
      naturalArea < MIN_NATURAL_AREA
    ) {
      return reject("below minimum natural dimensions");
    }

    const aspectRatio = naturalWidth / naturalHeight;
    const orientation =
      aspectRatio > 1.25
        ? "landscape"
        : aspectRatio < 0.8
          ? "portrait"
          : "near-square";

    return {
      candidate: true,
      reason: "visible image meets minimum natural dimensions",
      orientation,
      aspectRatio: Number(aspectRatio.toFixed(2)),
    };
  }

  globalThis.ACTImageDetector = Object.freeze({ classifyImage });
})();
