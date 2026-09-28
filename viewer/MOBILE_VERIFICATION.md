# Mobile verification boundary

This viewer treats iPhone-class Safari/touch use as a first-class client while keeping authoritative physics outside the browser.

## Deterministically verified in CI

- One-finger tap/orbit discrimination.
- Two-finger pinch/pan and suppression of accidental one-finger orbit after a pinch until the remaining finger is released.
- Edit-only touch placement gating; replay remains read-only.
- Responsive drawer selection for representative 375×667, 390×844, 430×932, 844×390, and 852×393 CSS-pixel viewports.
- Coarse-pointer/mobile rendering policy caps device pixel ratio and geometry detail without mutating simulation state.
- Safe-area CSS hooks for top/bottom/left/right browser and notch insets.
- Inspector vertical scrolling and toolbar horizontal scrolling use dedicated touch-action directions so form/panel gestures do not fall through to the WebGL canvas.
- The Inspector entry point and runtime replay-bundle file input remain present in the narrow layout.
- Compact form controls use 16 px text sizing and touch-sized targets to avoid common iOS focus zoom and undersized controls.

## Not verified by CI

The checks above emulate deterministic layout/gesture policy only. They do **not** establish that a physical iPhone Safari/WebGL run has succeeded. Device-level verification still needs a real device or browser-device service for:

- Safari/WebKit WebGL rendering and shader compatibility.
- Dynamic browser chrome and safe-area behavior while rotating the device.
- Native file/folder picker behavior for replay bundles.
- Touch latency, accidental gesture rates, and long-scroll ergonomics.
- Thermal throttling, memory pressure, and sustained battery/performance behavior.

## Physics boundary

Mobile rendering and UI degradation are display-only. The browser edits canonical SCENARIO intent and inspects canonical FRAME/replay results; it does not fabricate or replace authoritative solver physics.
