"use strict";

/*
 * Phase 3.4 — lazy observation registration tests.
 * Uses an injected observer factory, so no browser is required.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

require("../../extension/lib/lazy-observer.js");

const { DEFAULT_ROOT_MARGIN, createLazyObserver } = globalThis.ACTLazyObserver;

function fakeObserverFactory() {
  const instances = [];
  class FakeObserver {
    constructor(callback, options) {
      this.callback = callback;
      this.options = options;
      this.targets = [];
      this.disconnected = false;
      instances.push(this);
    }

    observe(target) {
      this.targets.push(target);
    }

    unobserve(target) {
      this.targets = this.targets.filter((entry) => entry !== target);
    }

    disconnect() {
      this.disconnected = true;
      this.targets = [];
    }

    fire(entries) {
      this.callback(entries, this);
    }
  }
  return { instances, factory: FakeObserver };
}

test("the default prefetch margin is conservative", () => {
  assert.equal(DEFAULT_ROOT_MARGIN, "800px 0px");
});

test("discovered images are registered with the observer once", () => {
  const { instances, factory } = fakeObserverFactory();
  const entered = [];
  const observer = createLazyObserver({
    onEnter: (image) => entered.push(image),
    observerFactory: factory,
  });
  const imageA = {};
  const imageB = {};

  assert.equal(observer.observe(imageA), true);
  assert.equal(observer.observe(imageB), true);
  assert.equal(observer.observe(imageA), false);

  assert.equal(instances.length, 1);
  assert.deepEqual(instances[0].targets, [imageA, imageB]);
  assert.equal(instances[0].options.rootMargin, DEFAULT_ROOT_MARGIN);
  assert.equal(observer.isObserved(imageA), true);
  assert.deepEqual(entered, []);
});

test("only intersecting entries are reported", () => {
  const { instances, factory } = fakeObserverFactory();
  const entered = [];
  const observer = createLazyObserver({
    onEnter: (image, entry) => entered.push([image, entry.isIntersecting]),
    rootMargin: "500px 0px",
    observerFactory: factory,
  });
  const image = {};
  observer.observe(image);

  instances[0].fire([{ target: image, isIntersecting: false }]);
  assert.deepEqual(entered, []);
  assert.equal(instances[0].options.rootMargin, "500px 0px");

  instances[0].fire([{ target: image, isIntersecting: true }]);
  assert.deepEqual(entered, [[image, true]]);
});

test("unobserve allows an image to be observed again", () => {
  const { instances, factory } = fakeObserverFactory();
  const observer = createLazyObserver({ onEnter: () => {}, observerFactory: factory });
  const image = {};

  observer.observe(image);
  assert.equal(observer.unobserve(image), true);
  assert.deepEqual(instances[0].targets, []);
  assert.equal(observer.isObserved(image), false);

  // A refreshed source must be able to force a fresh intersection callback.
  assert.equal(observer.observe(image), true);
  assert.deepEqual(instances[0].targets, [image]);
  assert.equal(observer.unobserve(image), true);
  assert.equal(observer.unobserve(image), false);
});

test("disconnect releases the observer and its registrations", () => {
  const { instances, factory } = fakeObserverFactory();
  const observer = createLazyObserver({ onEnter: () => {}, observerFactory: factory });
  const image = {};

  observer.observe(image);
  observer.disconnect();

  assert.equal(instances[0].disconnected, true);
  assert.equal(observer.isObserved(image), false);

  observer.observe(image);
  assert.equal(instances.length, 2);
  assert.deepEqual(instances[1].targets, [image]);
});

test("observation is a no-op when the platform has no IntersectionObserver", () => {
  const observer = createLazyObserver({
    onEnter: () => {},
    observerFactory: undefined,
  });

  assert.equal(observer.observe({}), false);
});
