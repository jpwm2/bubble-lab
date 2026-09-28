# Mobile WebKit verification boundary

This document records what `npm run test:webkit-mobile` establishes for the Bubble Lab viewer and, just as importantly, what it does not establish.

The harness runs the built viewer over a local HTTP server in an actual Playwright WebKit browser process. It does not replace the authoritative simulation backend, does not generate solver truth in the browser, and does not impersonate an iPhone or shipping Safari by overriding the user agent.

## Verified in CI/WebKit engine

When `npm run test:webkit-mobile` passes, the CI run has directly exercised all of the following in Playwright WebKit:

- Three iPhone-class CSS viewports: 390×844 portrait, 844×390 landscape, and 430×932 portrait.
- Mobile/touch browser-context characteristics exposed by the harness, while retaining the WebKit process's own user agent.
- Effective viewport, user agent, browser/WebKit version, device-pixel ratio, touch capability, coarse-pointer media-query state, and WebGL/WebGL2 availability are recorded in `test-results/webkit-mobile-observations.json`.
- The built viewer loads through HTTP, reaches its ready state, creates a non-zero 3D canvas, obtains WebGL/WebGL2, and completes without uncaught page errors.
- Compact drawer layout is selected for each profile, the Inspector opens and closes through browser touch automation, and the horizontal toolbar can be scrolled until its terminal control is reachable.
- The document does not overflow horizontally beyond a small pixel tolerance, and key toolbar controls expose practical 44 px-class touch boxes.
- The scenario/runtime Inspector remains vertically scrollable and keeps its `pan-y` interaction separate from the WebGL canvas; the compact toolbar retains `pan-x` and the canvas retains explicit gesture ownership.
- A primary scenario form field accepts input; backend and fidelity selectors operate; solid-boundary creation is reachable from the compact UI.
- A browser-delivered automated touch tap selects the centered bubble, while a browser drag/orbit sequence does not dispatch an accidental selection tap.
- The live canvas PointerEvent path is exercised with a two-pointer pinch sequence followed by a remaining-pointer move/release, confirming that the post-pinch path does not accidentally mutate selection.
- A deterministic replay bundle marked `TEST_FIXTURE` is loaded through the same runtime-bundle file-input path used by the product UI. Replay mutation controls remain disabled, frame/time information is visible, step/back and play/pause respond, and solver/provenance/feature-disclosure information is surfaced.

The two-frame replay under `test/fixtures/webkit-replay/` is deliberately test data. Its producer and event provenance say `TEST_FIXTURE`; it is browser-path evidence only and is not presented as solver output or physical validation.

The automated two-pointer sequence is not a claim of native hardware multi-touch. Playwright does not provide a true two-finger physical-touch gesture here, so that specific state-machine path is driven by PointerEvent dispatch through the live page event listeners and remains paired with the deterministic gesture unit tests.

## Still unverified

A passing WebKit-engine run does **not** establish any of the following:

- Physical iPhone hardware operation.
- Shipping Safari on iOS/iPadOS, including the exact WebKit build bundled with a particular OS release.
- Real-device Metal/WebKit GPU driver behavior, shader compilation quirks, memory-pressure behavior, or GPU process resets.
- Dynamic Safari browser chrome, home-indicator/notch interaction, and safe-area behavior beyond CSS viewport/safe-area emulation hooks.
- Native two-finger hardware gesture timing, finger rejection, touch latency, accidental gesture rates, or long-scroll ergonomics.
- Native iOS folder/file picker behavior for replay bundles.
- Device rotation transitions with real browser chrome rather than discrete CI viewport profiles.
- Thermal throttling, sustained memory pressure, battery consumption, or long-duration performance on an iPhone.

For those reasons, this harness strengthens the evidence for mobile support but does **not** mark R28 as fully satisfied. A physical-device/device-farm pass is still required before claiming iPhone Safari certification.

## Physics and provenance boundary

The mobile viewer remains a presentation/control client. Browser interaction edits canonical `SCENARIO` intent or inspects canonical `FRAME`/replay results. Rendering quality changes, WebKit verification, fixture playback, and UI interaction never become evidence that a missing physical phenomenon was solved. This preserves the physical-transparency boundary in R33 and the backend/viewer separation in R29.

## Requirement traceability

- **R3** — browser-level 3D touch selection and orbit interaction paths.
- **R19** — replay step and play/pause controls in WebKit.
- **R21** — the real renderer/debug-view surface boots with WebGL available.
- **R23 / R24** — Inspector and system/selection surfaces remain reachable and scrollable on compact viewports.
- **R27** — edit controls and replay read-only state remain distinct.
- **R28** — strengthened with real WebKit-engine evidence at iPhone-class viewports, while physical iPhone Safari remains explicitly unverified.
- **R29** — replay bundle uses the existing result/viewer boundary and does not execute physics in-browser.
- **R31** — deterministic `TEST_FIXTURE` replay data and recorded browser observations make the browser-path check repeatable.
- **R33** — fixture, viewer-derived, and still-unverified claims remain explicitly labeled.
- **R38** — adds integrated mobile-browser evidence without treating page rendering alone as integrated physical completion.

## Commands

The worker acceptance path is:

```sh
cd bubblelab/viewer
npm ci
npm run typecheck
npm run test
npm run test:mobile
npm run test:webkit-mobile
npm run test:lab-ui
npm run test:runtime-bundle
npm run build
```

`test:webkit-mobile` builds the viewer, installs the pinned Playwright WebKit browser plus required Linux dependencies, serves `dist/` locally, executes the browser checks above, and writes the observation JSON under `test-results/`.
