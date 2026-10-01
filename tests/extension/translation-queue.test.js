"use strict";

/*
 * Phase 3.4 — bounded lazy translation queue unit tests.
 * Covers queue lifecycle, deduplication, bounded concurrency, failure
 * isolation, and cleanup bookkeeping. No browser and no backend required.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

require("../../extension/lib/translation-queue.js");

const { DEFAULT_MAX_CONCURRENT, SKIP, STATE, createTranslationQueue } =
  globalThis.ACTTranslationQueue;

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const flush = () => new Promise((resolve) => setImmediate(resolve));

function recorder() {
  const events = [];
  return { events, onEvent: (event, detail) => events.push({ event, ...detail }) };
}

test("default concurrency is one", () => {
  assert.equal(DEFAULT_MAX_CONCURRENT, 1);
});

test("a queued image is processed once and stores its result", async () => {
  const { events, onEvent } = recorder();
  const image = {};
  const result = { payload: { regions: [] }, requestId: "abc" };
  const seen = [];
  const queue = createTranslationQueue({
    runTask: async (target) => {
      seen.push(target);
      return result;
    },
    onEvent,
  });

  assert.equal(queue.enqueue(image), true);
  assert.equal(queue.stateOf(image), STATE.PROCESSING);
  await flush();

  assert.deepEqual(seen, [image]);
  assert.equal(queue.stateOf(image), STATE.SUCCESS);
  assert.deepEqual(queue.resultOf(image), { status: STATE.SUCCESS, result });
  assert.deepEqual(
    events.map(({ event }) => event),
    ["queued", "processing", "completed"],
  );
  assert.equal(events[0].state, STATE.QUEUED);
  assert.deepEqual(queue.stats(), { active: 0, pending: 0, maxConcurrent: 1 });
});

test("the same image cannot be queued twice while work is outstanding", async () => {
  const gate = deferred();
  const image = {};
  let runs = 0;
  const queue = createTranslationQueue({
    runTask: async () => {
      runs += 1;
      await gate.promise;
      return {};
    },
  });

  assert.equal(queue.enqueue(image), true);
  assert.equal(queue.enqueue(image), false);
  await flush();
  assert.equal(runs, 1);
  assert.equal(queue.stats().active, 1);

  gate.resolve();
  await flush();
  assert.equal(runs, 1);
  assert.equal(queue.stats().active, 0);

  // A finished image is terminal for automatic queueing.
  assert.equal(queue.enqueue(image), false);
  assert.equal(runs, 1);
});

test("processing respects the configured concurrency and preserves FIFO order", async () => {
  const imageA = {};
  const imageB = {};
  const imageC = {};
  const gates = new Map([
    [imageA, deferred()],
    [imageB, deferred()],
    [imageC, deferred()],
  ]);
  const started = [];
  const queue = createTranslationQueue({
    maxConcurrent: 2,
    runTask: async (image) => {
      started.push(image);
      await gates.get(image).promise;
      return {};
    },
  });

  queue.enqueue(imageA);
  queue.enqueue(imageB);
  queue.enqueue(imageC);
  await flush();

  assert.deepEqual(started, [imageA, imageB]);
  assert.equal(queue.stats().active, 2);
  assert.equal(queue.stats().pending, 1);
  assert.equal(queue.stateOf(imageC), STATE.QUEUED);

  gates.get(imageA).resolve();
  await flush();
  assert.deepEqual(started, [imageA, imageB, imageC]);
  assert.equal(queue.stateOf(imageA), STATE.SUCCESS);
  assert.equal(queue.stats().active, 2);

  gates.get(imageB).resolve();
  gates.get(imageC).resolve();
  await flush();
  assert.equal(queue.stats().active, 0);
  assert.equal(queue.stats().pending, 0);
});

test("the second image waits for the first and then starts", async () => {
  const imageA = {};
  const imageB = {};
  const gate = deferred();
  const started = [];
  const queue = createTranslationQueue({
    runTask: async (image) => {
      started.push(image);
      if (image === imageA) {
        await gate.promise;
      }
      return {};
    },
  });

  queue.enqueue(imageA);
  queue.enqueue(imageB);
  await flush();

  assert.deepEqual(started, [imageA]);
  assert.equal(queue.stateOf(imageB), STATE.QUEUED);
  assert.equal(queue.stats().active, 1);

  gate.resolve();
  await flush();

  assert.deepEqual(started, [imageA, imageB]);
  assert.equal(queue.stateOf(imageA), STATE.SUCCESS);
  assert.equal(queue.stateOf(imageB), STATE.SUCCESS);
  assert.equal(queue.stats().active, 0);
});

test("a failure releases the worker slot and later images still process", async () => {
  const imageA = {};
  const imageB = {};
  const imageC = {};
  const failure = new Error("backend offline");
  const { events, onEvent } = recorder();
  const queue = createTranslationQueue({
    runTask: async (image) => {
      if (image === imageA) {
        throw failure;
      }
      return {};
    },
    onEvent,
  });

  queue.enqueue(imageA);
  queue.enqueue(imageB);
  queue.enqueue(imageC);
  await flush();

  assert.equal(queue.stateOf(imageA), STATE.ERROR);
  assert.deepEqual(queue.resultOf(imageA), { status: STATE.ERROR, error: failure });
  assert.equal(queue.stateOf(imageB), STATE.SUCCESS);
  assert.equal(queue.stateOf(imageC), STATE.SUCCESS);
  assert.equal(queue.stats().active, 0);
  assert.deepEqual(
    events.filter(({ event }) => event === "failed").map(({ image }) => image),
    [imageA],
  );

  // An errored image is not retried automatically.
  assert.equal(queue.enqueue(imageA), false);
  await flush();
  assert.equal(queue.stateOf(imageA), STATE.ERROR);
});

test("a manual trigger can retry an errored image but never re-runs a success", async () => {
  const image = {};
  let runs = 0;
  const queue = createTranslationQueue({
    runTask: async () => {
      runs += 1;
      if (runs === 1) {
        throw new Error("timeout");
      }
      return {};
    },
  });

  queue.enqueue(image);
  await flush();
  assert.equal(runs, 1);
  assert.equal(queue.stateOf(image), STATE.ERROR);

  assert.equal(queue.enqueue(image, { manual: true }), true);
  await flush();
  assert.equal(runs, 2);
  assert.equal(queue.stateOf(image), STATE.SUCCESS);

  assert.equal(queue.enqueue(image, { manual: true }), false);
  await flush();
  assert.equal(runs, 2);
});

test("ineligible images are skipped without consuming a worker slot", async () => {
  const blocked = {};
  const imageA = {};
  const gate = deferred();
  const started = [];
  const { events, onEvent } = recorder();
  const eligible = new WeakSet();
  const queue = createTranslationQueue({
    runTask: async (image) => {
      started.push(image);
      await gate.promise;
      return {};
    },
    isEligible: (image) => eligible.has(image),
    onEvent,
  });

  // Ineligible at enqueue time.
  assert.equal(queue.enqueue(blocked), false);
  assert.equal(
    events.at(-1).reason,
    "ineligible",
  );
  assert.equal(queue.stateOf(blocked), STATE.IDLE);

  // Eligible at enqueue time, detached before the slot frees up.
  eligible.add(imageA);
  eligible.add(blocked);
  queue.enqueue(imageA);
  queue.enqueue(blocked);
  await flush();
  assert.deepEqual(started, [imageA]);
  assert.equal(queue.stateOf(blocked), STATE.QUEUED);

  eligible.delete(blocked);
  gate.resolve();
  await flush();

  assert.deepEqual(started, [imageA]);
  assert.equal(queue.stateOf(blocked), STATE.IDLE);
  assert.equal(queue.stats().active, 0);
  assert.equal(queue.stats().pending, 0);
});

test("a skipped task returns the image to idle without an error", async () => {
  const image = {};
  const { events, onEvent } = recorder();
  const queue = createTranslationQueue({
    runTask: async () => SKIP,
    onEvent,
  });

  queue.enqueue(image);
  await flush();

  assert.equal(queue.stateOf(image), STATE.IDLE);
  assert.equal(queue.resultOf(image), null);
  assert.equal(events.at(-1).event, "skipped");
  assert.equal(events.at(-1).reason, "not-eligible");

  // The slot is free, so the image can be queued again later.
  assert.equal(queue.enqueue(image), true);
  await flush();
});

test("forget invalidates in-flight work and stale results", async () => {
  const image = {};
  const gate = deferred();
  const queue = createTranslationQueue({
    runTask: async () => {
      await gate.promise;
      return { payload: {} };
    },
  });

  queue.enqueue(image);
  await flush();
  assert.equal(queue.stateOf(image), STATE.PROCESSING);

  queue.forget(image);
  assert.equal(queue.stateOf(image), STATE.IDLE);

  gate.resolve();
  await flush();

  assert.equal(queue.stateOf(image), STATE.IDLE);
  assert.equal(queue.resultOf(image), null);
  assert.equal(queue.stats().active, 0);
});

test("cancel removes a queued image and reset never goes negative", async () => {
  const imageA = {};
  const imageB = {};
  const gate = deferred();
  const started = [];
  const queue = createTranslationQueue({
    runTask: async (image) => {
      started.push(image);
      await gate.promise;
      return {};
    },
  });

  queue.enqueue(imageA);
  queue.enqueue(imageB);
  await flush();
  assert.deepEqual(started, [imageA]);

  assert.equal(queue.cancel(imageB), true);
  assert.equal(queue.stateOf(imageB), STATE.IDLE);
  assert.equal(queue.stats().pending, 0);
  assert.equal(queue.cancel(imageB), false);

  // Resetting while a task is in flight must not leave stale bookkeeping.
  queue.reset();
  assert.deepEqual(queue.stats(), { active: 0, pending: 0, maxConcurrent: 1 });

  gate.resolve();
  await flush();
  assert.equal(queue.stats().active, 0);
  assert.equal(queue.stateOf(imageA), STATE.IDLE);
});

test("reset keeps completed results when asked, so a resume does not retranslate", async () => {
  const succeeded = {};
  const failed = {};
  const interrupted = {};
  const gate = deferred();
  let runs = 0;
  const queue = createTranslationQueue({
    runTask: async (image) => {
      runs += 1;
      if (image === interrupted) {
        await gate.promise;
      }
      if (image === failed) {
        throw new Error("backend offline");
      }
      return { payload: {} };
    },
  });

  queue.enqueue(succeeded);
  queue.enqueue(failed);
  await flush();
  queue.enqueue(interrupted);
  await flush();
  assert.equal(queue.stateOf(succeeded), STATE.SUCCESS);
  assert.equal(queue.stateOf(failed), STATE.ERROR);
  assert.equal(queue.stateOf(interrupted), STATE.PROCESSING);

  queue.reset({ keepResults: true });

  // Completed work is preserved; transient work is dropped.
  assert.equal(queue.stateOf(succeeded), STATE.SUCCESS);
  assert.equal(queue.stateOf(failed), STATE.ERROR);
  assert.equal(queue.stateOf(interrupted), STATE.IDLE);
  assert.deepEqual(queue.stats(), { active: 0, pending: 0, maxConcurrent: 1 });

  // A resume reuses the stored result and does not retranslate.
  assert.equal(queue.enqueue(succeeded), false);
  assert.equal(runs, 3);
  assert.deepEqual(queue.resultOf(succeeded), {
    status: STATE.SUCCESS,
    result: { payload: {} },
  });

  gate.resolve();
  await flush();
  assert.equal(queue.stats().active, 0);
  assert.equal(queue.stateOf(interrupted), STATE.IDLE);
});

test("concurrency bookkeeping never exceeds the configured limit", async () => {
  const images = [{}, {}, {}, {}];
  const gates = images.map(() => deferred());
  let concurrent = 0;
  let peak = 0;
  const queue = createTranslationQueue({
    maxConcurrent: 2,
    runTask: async (image) => {
      concurrent += 1;
      peak = Math.max(peak, concurrent);
      await gates[images.indexOf(image)].promise;
      concurrent -= 1;
      return {};
    },
  });

  for (const image of images) {
    queue.enqueue(image);
  }
  await flush();
  assert.equal(queue.stats().active, 2);
  assert.equal(queue.stats().pending, 2);
  assert.ok(queue.stats().active <= 2);

  for (const gate of gates) {
    gate.resolve();
  }
  await flush();

  assert.equal(peak, 2);
  assert.equal(queue.stats().active, 0);
  assert.equal(queue.stats().pending, 0);
});
