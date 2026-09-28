import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import {
  TAP_SLOP_PX,
  canCommitPlacementTap,
  createGestureState,
  gesturePointerDown,
  gesturePointerMove,
  gesturePointerUp,
  isTapWithinThreshold,
  selectLayoutPolicy,
  selectRenderingPolicy,
} from "../.build/src/mobile.js";

test("tap threshold distinguishes selection taps from camera drags", () => {
  assert.equal(isTapWithinThreshold({ x: 10, y: 10 }, { x: 10 + TAP_SLOP_PX, y: 10 }), true);
  assert.equal(isTapWithinThreshold({ x: 10, y: 10 }, { x: 10 + TAP_SLOP_PX + 0.01, y: 10 }), false);
});

test("one pointer remains a tap candidate until threshold then becomes orbit", () => {
  let step = gesturePointerDown(createGestureState(), 1, { x: 20, y: 30 });
  assert.equal(step.state.mode, "TAP_CANDIDATE");
  step = gesturePointerMove(step.state, 1, { x: 24, y: 33 });
  assert.equal(step.state.mode, "TAP_CANDIDATE");
  assert.equal(step.action.type, "NONE");
  step = gesturePointerMove(step.state, 1, { x: 36, y: 35 });
  assert.equal(step.state.mode, "ORBIT");
  assert.equal(step.action.type, "ORBIT");
  assert.notEqual(step.action.type === "ORBIT" ? step.action.dx : 0, 0);
  const released = gesturePointerUp(step.state, 1, { x: 36, y: 35 });
  assert.equal(released.tap, null);
});

test("single short touch resolves to a deterministic tap", () => {
  const down = gesturePointerDown(createGestureState(), 1, { x: 100, y: 100 });
  const move = gesturePointerMove(down.state, 1, { x: 103, y: 102 });
  const up = gesturePointerUp(move.state, 1, { x: 103, y: 102 });
  assert.deepEqual(up.tap, { x: 103, y: 102 });
  assert.equal(up.state.mode, "IDLE");
});

test("two pointers transition to pinch-pan and latch the remaining finger until release", () => {
  let step = gesturePointerDown(createGestureState(), 1, { x: 0, y: 0 });
  step = gesturePointerDown(step.state, 2, { x: 100, y: 0 });
  assert.equal(step.state.mode, "PINCH_PAN");
  step = gesturePointerMove(step.state, 2, { x: 120, y: 10 });
  assert.equal(step.action.type, "PINCH_PAN");
  if (step.action.type === "PINCH_PAN") {
    assert.ok(step.action.zoomFactor < 1);
    assert.ok(step.action.panDx > 0);
    assert.ok(step.action.panDy > 0);
  }
  const oneLeft = gesturePointerUp(step.state, 2, { x: 120, y: 10 });
  assert.equal(oneLeft.tap, null);
  assert.equal(oneLeft.state.mode, "POST_PINCH");
  const suppressed = gesturePointerMove(oneLeft.state, 1, { x: 30, y: 20 });
  assert.equal(suppressed.state.mode, "POST_PINCH");
  assert.equal(suppressed.action.type, "NONE");
  const final = gesturePointerUp(suppressed.state, 1, { x: 30, y: 20 });
  assert.equal(final.tap, null);
  assert.equal(final.state.mode, "IDLE");
});

test("add placement gating rejects replay edits and non-tap gestures", () => {
  assert.equal(canCommitPlacementTap("EDIT", true, true), true);
  assert.equal(canCommitPlacementTap("EDIT", false, true), false);
  assert.equal(canCommitPlacementTap("EDIT", true, false), false);
  assert.equal(canCommitPlacementTap("REPLAY", true, true), false);
});

test("rendering profiles cap DPR without mutating physical data", () => {
  const battery = selectRenderingPolicy("BATTERY", 390, 844, 3, true);
  assert.equal(battery.targetPixelRatio, 1);
  assert.equal(battery.expensiveOptics, false);
  assert.equal(battery.sphereWidthSegments, 20);

  const automatic = selectRenderingPolicy("AUTO", 390, 844, 3, true);
  assert.equal(automatic.targetPixelRatio, 1.5);
  assert.equal(automatic.expensiveOptics, true);

  const quality = selectRenderingPolicy("QUALITY", 1200, 900, 3, false);
  assert.equal(quality.targetPixelRatio, 2.5);
  assert.equal(quality.expensiveOptics, true);
});

test("layout policy covers representative iPhone-class portrait and landscape sizes", () => {
  for (const [width, height, orientation] of [
    [375, 667, "PORTRAIT"],
    [390, 844, "PORTRAIT"],
    [430, 932, "PORTRAIT"],
    [844, 390, "LANDSCAPE"],
    [852, 393, "LANDSCAPE"],
  ]) {
    assert.deepEqual(selectLayoutPolicy(width, height), { orientation, inspector: "DRAWER", compact: true });
  }
  assert.deepEqual(selectLayoutPolicy(1280, 800), { orientation: "LANDSCAPE", inspector: "SIDEBAR", compact: false });
});

test("mobile assets preserve safe areas, scrollable controls, and reachable replay import", async () => {
  const styles = await readFile(new URL("../src/styles.css", import.meta.url), "utf8");
  const html = await readFile(new URL("../index.html", import.meta.url), "utf8");

  assert.match(styles, /env\(safe-area-inset-top\)/);
  assert.match(styles, /env\(safe-area-inset-bottom\)/);
  assert.match(styles, /touch-action:\s*pan-y/);
  assert.match(styles, /overflow-x:\s*auto/);
  assert.match(styles, /touch-action:\s*pan-x/);
  assert.match(styles, /\.panel input,[\s\S]*font-size:\s*16px/);
  assert.match(html, /class="runtime-bundle-label"/);
  assert.ok(html.indexOf('id="inspector-toggle"') < html.indexOf('id="mode-edit"'));
});
