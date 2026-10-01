/*
 * Phase 3.4 — bounded lazy translation queue.
 *
 * Small, dependency-free FIFO queue with per-image state tracking. It owns no
 * DOM knowledge and no backend knowledge: the caller supplies `runTask(image)`
 * (the existing Phase 3.3 translation path) and `isEligible(image)`.
 *
 * Lifecycle per image:
 *   idle -> queued -> processing -> success | error
 *
 * A successfully translated image is terminal for the page session. An errored
 * image is terminal for automatic queueing (no retry storm) but can be retried
 * by an explicit manual trigger (Alt+Click).
 */
(() => {
  const STATE = Object.freeze({
    IDLE: "idle",
    QUEUED: "queued",
    PROCESSING: "processing",
    SUCCESS: "success",
    ERROR: "error",
  });

  const DEFAULT_MAX_CONCURRENT = 1;

  // Returned by a task that decided not to translate (image detached, source
  // changed, translator disabled). The queue returns the image to `idle`
  // instead of recording an error.
  const SKIP = Symbol("ACT_QUEUE_SKIP");

  function createTranslationQueue({
    maxConcurrent = DEFAULT_MAX_CONCURRENT,
    runTask,
    isEligible = () => true,
    onEvent = () => {},
  } = {}) {
    if (typeof runTask !== "function") {
      throw new TypeError("A runTask function is required.");
    }
    const limit =
      Number.isFinite(maxConcurrent) && maxConcurrent >= 1
        ? Math.floor(maxConcurrent)
        : DEFAULT_MAX_CONCURRENT;

    let states = new WeakMap();
    let results = new WeakMap();
    let epochs = new WeakMap();
    let manualFlags = new WeakMap();
    let pending = [];
    let inFlight = new Set();
    let active = 0;
    let generation = 0;

    function stateOf(image) {
      return states.get(image) || STATE.IDLE;
    }

    function resultOf(image) {
      return results.get(image) || null;
    }

    function setState(image, state) {
      if (state === STATE.IDLE) {
        states.delete(image);
      } else {
        states.set(image, state);
      }
    }

    function bumpEpoch(image) {
      const epoch = (epochs.get(image) || 0) + 1;
      epochs.set(image, epoch);
      return epoch;
    }

    function isManual(image) {
      return manualFlags.get(image) === true;
    }

    function notify(event, image, detail) {
      onEvent(event, { image, manual: isManual(image), ...detail });
    }

    function enqueue(image, { manual = false } = {}) {
      if (!image) {
        return false;
      }

      const state = stateOf(image);
      if (state === STATE.SUCCESS) {
        notify("reused", image, { manual, state, reason: "already-translated" });
        return false;
      }
      if (state === STATE.QUEUED || state === STATE.PROCESSING) {
        notify("skipped", image, {
          manual,
          state,
          reason: "already-in-progress",
        });
        return false;
      }
      if (state === STATE.ERROR && !manual) {
        notify("skipped", image, { manual, state, reason: "previous-error" });
        return false;
      }
      if (!isEligible(image)) {
        notify("skipped", image, { manual, state, reason: "ineligible" });
        return false;
      }

      manualFlags.set(image, manual);
      setState(image, STATE.QUEUED);
      pending.push(image);
      inFlight.add(image);
      notify("queued", image, { state: STATE.QUEUED });
      pump();
      return true;
    }

    function pump() {
      while (active < limit && pending.length > 0) {
        const image = pending.shift();
        if (!isEligible(image)) {
          // The image was removed or changed while it waited. Skip it cleanly
          // so it cannot hold a worker slot.
          inFlight.delete(image);
          setState(image, STATE.IDLE);
          notify("skipped", image, { state: STATE.IDLE, reason: "ineligible" });
          continue;
        }
        start(image);
      }
    }

    function start(image) {
      const gen = generation;
      const epoch = bumpEpoch(image);
      const manual = isManual(image);
      active += 1;
      setState(image, STATE.PROCESSING);
      notify("processing", image, { state: STATE.PROCESSING });

      Promise.resolve()
        .then(() => runTask(image, { manual }))
        .then(
          (result) => {
            if (gen !== generation || epochs.get(image) !== epoch) {
              return;
            }
            inFlight.delete(image);
            if (result === SKIP) {
              setState(image, STATE.IDLE);
              notify("skipped", image, { state: STATE.IDLE, reason: "not-eligible" });
              return;
            }
            results.set(image, { status: STATE.SUCCESS, result });
            setState(image, STATE.SUCCESS);
            notify("completed", image, { state: STATE.SUCCESS, result });
          },
          (error) => {
            if (gen !== generation || epochs.get(image) !== epoch) {
              return;
            }
            inFlight.delete(image);
            results.set(image, { status: STATE.ERROR, error });
            setState(image, STATE.ERROR);
            notify("failed", image, { state: STATE.ERROR, error });
          },
        )
        .then(() => {
          if (gen !== generation) {
            return;
          }
          active = Math.max(0, active - 1);
          pump();
        });
    }

    function cancel(image) {
      if (stateOf(image) !== STATE.QUEUED) {
        return false;
      }
      pending = pending.filter((entry) => entry !== image);
      inFlight.delete(image);
      setState(image, STATE.IDLE);
      notify("skipped", image, { state: STATE.IDLE, reason: "cancelled" });
      return true;
    }

    // Drop all knowledge of an image (used when its source changes or it is
    // removed). In-flight work for that image is invalidated so it cannot
    // write a stale result back into the queue.
    function forget(image) {
      pending = pending.filter((entry) => entry !== image);
      inFlight.delete(image);
      bumpEpoch(image);
      states.delete(image);
      results.delete(image);
    }

    /*
     * `keepResults` preserves completed per-image results (and their `success`
     * or `error` state) so that pausing and resuming the translator does not
     * retranslate images that already succeeded. Transient work is always
     * dropped and cannot be resumed.
     */
    function reset({ keepResults = false } = {}) {
      generation += 1;
      pending = [];
      if (keepResults) {
        for (const image of inFlight) {
          states.delete(image);
        }
        manualFlags = new WeakMap();
      } else {
        states = new WeakMap();
        results = new WeakMap();
        epochs = new WeakMap();
        manualFlags = new WeakMap();
      }
      inFlight = new Set();
      active = 0;
    }

    function stats() {
      return { active, pending: pending.length, maxConcurrent: limit };
    }

    return Object.freeze({
      STATE,
      SKIP,
      maxConcurrent: limit,
      enqueue,
      cancel,
      forget,
      reset,
      stateOf,
      resultOf,
      stats,
    });
  }

  globalThis.ACTTranslationQueue = Object.freeze({
    DEFAULT_MAX_CONCURRENT,
    STATE,
    SKIP,
    createTranslationQueue,
  });
})();
