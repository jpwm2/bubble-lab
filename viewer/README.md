# Bubble Lab Web viewer — canonical contract integration and thin-film optics

The viewer consumes Bubble Lab contract-v1 `FRAME`/`CHECKPOINT` results and an editable contract-v1 `SCENARIO` without introducing a viewer-specific physical-state format. Rendering state is deliberately separate from simulation state: optical appearance may improve observation, but it cannot create pressure, curvature, film thickness, topology, or other physics.

## Run

```bash
npm ci
npm run typecheck
npm run test
npm run test:contract
npm run test:lab-ui
npm run test:debug
npm run test:optics
npm run test:mobile
npm run test:runtime-bundle
npm run build
python3 -m http.server 8000 -d dist
```

## Data boundary

- `contract.ts` performs the viewer-side contract-version/kind boundary checks.
- `adapter.ts` is the narrow contract-to-render adapter. Three.js objects are never authoritative state.
- `fixtures.ts` loads the accepted canonical fixtures copied into `dist/fixtures` by the build; the repository fixtures remain the source of truth.
- `replay.ts` owns ordered exact-frame replay. It never interpolates or changes physical values.
- `store.ts` owns editable `SCENARIO` state. Editor add/delete operations never mutate a loaded authoritative `FRAME`.
- `lab.ts` owns deterministic scientific-lab preparation semantics: explicit scenario/replay modes, supported runtime configuration mapping, feature gating, canonical burst intent, deterministic serialization, runtime invocation descriptors, event lineage, and responsive lab-panel policy.
- `renderer.ts` renders inline canonical meshes directly. A sphere is used only when an alive bubble has no renderable outer mesh and is explicitly identified in the inspector as `VIEWER_SPHERE_FALLBACK`.
- SIDECAR mesh references remain disclosed but are not silently replaced with invented mesh geometry.

## Bubble Lab scenario and runtime workflow

The browser is a **scenario preparation and result-inspection client**, not the authoritative physics runtime. The lab workflow keeps three explicit application states:

- `EDIT_SCENARIO`: edit canonical SCENARIO intent such as bubble radius/volume, position, supported gas fields, gravity, wind/background velocity, requested backend/fidelity, output cadence, thin-film transport parameters, and accepted event settings.
- `REVIEW_SCENARIO`: inspect the prepared deterministic scenario before handoff. Unsupported backend/feature combinations are rejected before a runtime command is generated.
- `REVIEW_REPLAY`: inspect authoritative FRAME/replay output. A replay bundle carries its source scenario ID/hash and backend identity; historical FRAME data remains read-only.

`lab.ts` maps controls only onto keys already accepted by the canonical/runtime conventions. Thin-film configuration uses `user_editable.thinfilm`; output cadence uses `user_editable.runtime.output_cadence_s`; rupture settings use the accepted `user_editable.events` keys. A user burst request is recorded as future/current runtime intent (`enable_rupture`, `allow_user_trigger`, `user_trigger_time_s`) rather than deleting or visually rupturing a loaded FRAME.

Capability disclosure has two sources and never infers physics support from the presence of a control. Before a run, the viewer uses documented accepted runtime knowledge to label a feature as honored, rejected, or requiring another backend. After a result is loaded, the result manifest's `RESOLVED` / `MODELED` / `VISUAL_ONLY` / `NOT_IMPLEMENTED` declarations are authoritative.

The accepted browser-to-runtime handoff is:

1. Edit the canonical SCENARIO.
2. Validate the selected backend and feature combination locally as far as the viewer contract/runtime knowledge permits.
3. Serialize/export the SCENARIO deterministically.
4. Generate a command descriptor for the external Python runtime, for example:

   ```bash
   python3 bubblelab/runtime/tools/run_scenario.py 'scenario.json' --backend transient --output 'replay-output' --frames 4
   ```

5. Execute that command outside the browser.
6. Load the generated replay bundle folder (`replay.json` plus FRAME files) into the viewer.
7. Review exact frames, solver diagnostics, topology events, lineage, fields, optical provenance, and feature disclosures.

The invocation descriptor always reports `executesInBrowser: false`. There is intentionally no fake Run action that merely animates viewer geometry and presents it as solver output.

`npm run test:lab-ui` covers deterministic scenario edits/serialization, unsupported-feature gating, scenario-vs-FRAME separation, thin-film mapping, user-burst/event mapping, backend/fidelity selection, capability disclosure, external invocation generation, replay mode transition/source tracking, event parent/child lineage, and mobile lab-panel policy.

## Optical model

The reference optical calculations live in pure functions in `optics.ts`; the browser material uses the same inputs and provenance policy.

For an interface between refractive indices (n_1) and (n_2), the exact normal-incidence intensity reflectance is

```text
R0 = ((n1 - n2) / (n1 + n2))^2
```

and `fresnelSchlick` uses

```text
R(theta) ~= R0 + (1 - R0) (1 - cos(theta))^5
```

when an inexpensive scalar Fresnel approximation is useful. The Three.js `MeshPhysicalMaterial` receives the film IOR directly, so its transparent surface shading also has angle-dependent dielectric reflection rather than an arbitrary rim-light term.

For a film with physical thickness (d), film index (n), transmitted angle (\theta_t), and vacuum wavelength (lambda), the interference phase used by the reference calculation is

```text
delta = 4 pi n d cos(theta_t) / lambda
```

with the transmitted angle obtained from Snell's law. The pure reference function computes unpolarized thin-film reflectance from the s- and p-polarized interface amplitude coefficients for an air / liquid-film / air stack. `thinFilmRgb` samples seven visible wavelengths from 420–660 nm, weights them with broad RGB sensitivity approximations, and converts the resulting linear values to sRGB. This is a compact display approximation, not a colorimetric spectrophotometer model.

The interactive renderer uses Three.js physical transmission, IOR-based Fresnel response, a PMREM environment reflection, double-sided thin surfaces, and the renderer's iridescence support. Scalar thickness sets one interference thickness. Inline per-vertex and per-face fields are preserved as viewer attributes and mapped to the material's iridescence-thickness channel without writing smoothed values back to the contract.

The renderer optical constant for the liquid film is (n = 1.333). It is a presentation-model parameter unless a future canonical contract defines an optical refractive-index field; it is never stored back into solver state.

## Thickness provenance rules

The viewer recognizes authoritative thickness only from canonical data:

- a film-region scalar explicitly expressed in metres, such as `value_m`, `thickness_m`, `scalar_m`, `mean_m`, or `{ value, unit: "m" }`;
- an inline mesh field explicitly referenced by the film region through `field`, `field_name`, or `mesh_field`;
- conventional inline field names `film_thickness_m` or `thickness_m`;
- an explicitly supplied canonical bubble `film_thickness_m` extension, when present.

A field with exactly one value per mesh vertex is treated as a vertex field; one value per face is treated as a face field. Values are preserved. Screen-space depth, bubble radius, curvature, mesh size, and color cycles are never converted into a physical thickness.

In `AUTO` mode, a `RESOLVED` thickness disclosure is labeled physical/resolved and a `MODELED` disclosure is labeled physical/modeled. A manifest declaring `film_thickness: NOT_IMPLEMENTED` or `VISUAL_ONLY` blocks canonical values from being presented as physically driven interference. A canonical `SCENARIO` can carry user/import thickness before a solver manifest exists; the viewer labels that source `CONTRACT_INPUT`, not `RESOLVED`.

When no usable authoritative thickness exists, the default is neutral transparent Fresnel/transmission rendering with interference disabled. The user may explicitly select `VISUAL_ONLY preview` and choose a display thickness in nanometres. That value exists only in viewer state and is never written to a scenario, frame, checkpoint, replay, or solver field.

## Film and geometry observation modes

The display controls provide:

- all films, outer films only, shared films only, or no films;
- canonical mesh visibility independently from viewer sphere-fallback visibility;
- a wireframe overlay that does not replace the transparent optical surface;
- optional junction / Plateau-border geometry;
- scalar debug channels independently from the thin-film optical layer.

Shared films use a distinct observational tint/opacity so topology is easier to inspect. That distinction does not encode an uncomputed pressure, tension, thickness, or other physical scalar.

## Scientific physics-debug explorer

Replay FRAMEs expose a provenance-aware scientific debug layer without creating a second simulation-state format. The viewer discovers inline canonical mesh fields directly from `surface_meshes[].fields`, classifies their association from the declared array shape and mesh counts, and keeps the source path visible in the inspector.

### Mesh and topology debug modes

The collapsible debug controls independently expose triangle faces, wireframe/edges, deterministically subsampled vertices, outer/shared film visibility, junction/triple-line geometry, sphere fallbacks, vertex normals, and face normals. Shared-film geometry and junction lines remain directly selectable when their canonical geometry is present. Selection resolves the canonical film-region ID/kind/adjacency or junction ID/incident-film list and shows measured junction angles only when the FRAME supplies them.

If a canonical vertex/face normal vector field exists, that field is used for the matching mesh. Otherwise the normal overlay is a `VIEWER_DERIVED` geometry diagnostic computed from render geometry. Derived normals are never labeled as curvature, force, stress, traction, or solver output.

### Scalar fields

The scalar explorer supports canonical per-vertex and per-face inline fields, plus bubble/film quantities when their entity mapping is unambiguous. It reports finite/missing counts, minimum, maximum, mean, source path, association, units when inferable from the canonical field name, input provenance, feature disclosure, and provenance class.

Automatic ranges use the finite values in the selected canonical field. Manual ranges are accepted only when both endpoints are finite and maximum is greater than minimum. A requested diverging scale becomes symmetric around zero only for a signed range that actually crosses zero. NaN and non-finite inputs are not silently converted to zero.

A manifest disclosure of `NOT_IMPLEMENTED` makes the corresponding discovered field unavailable for physical coloring even when a similarly named payload happens to be present. `VISUAL_ONLY`, solver diagnostic, and canonical physical quantities remain visibly distinct.

### Vector fields and display sampling

The vector explorer discovers canonical Nx3 mesh vectors, bubble velocity, gravity, and wind when present. Mesh vectors are anchored to their declared vertex/face association; bubble vectors are anchored to canonical centroids; environment vectors originate at the viewer origin as an observation aid. No force or traction field is synthesized when one is absent.

Glyph count, scale, and normalization are display controls only. Large point/vector overlays use deterministic index subsampling and never decimate, reorder, or mutate canonical arrays. Surface geometry is cached per source/frame/mesh so changing debug layers does not rebuild unchanged canonical mesh geometry unnecessarily.

### Solver, AMR, and remeshing diagnostics

The system inspector shows shared-film, junction, and topology-event counts; fidelity tier; solver/backend identity; active feature disclosures; residuals; timestep; nonlinear/linear iteration counts; compute time; and maximum volume error when supplied.

Flexible diagnostics are searched conservatively for AMR metadata such as active cells by level, maximum refinement level, finest spacing, refinement criterion, and pressure/divergence residuals, and for remeshing counts/mesh sizes/quality/volume-change/scalar-transfer-error metadata. These are shown as numeric/text metadata only. The viewer does not invent spatial AMR boxes, remeshing operations, or solver fields.

Per-bubble selection also exposes available temperature, gas amount, contact count, area, relative volume error, pressure, centroid, velocity, volume, and equivalent radius. Missing optional values remain `Unavailable`.

### Debug verification boundary

`npm run test:debug` covers field discovery, vertex/face association, missing/NaN statistics, automatic/manual/signed ranges, provenance and `NOT_IMPLEMENTED` gating, deterministic vector/vertex subsampling, system summary counts, AMR/remeshing metadata extraction, shared-film/junction topology mapping, and explicit `VIEWER_DERIVED` normal classification.

The debug tests validate pure/data behavior. They do not replace physical-device WebGL/Safari verification, nor do overlays provide evidence that a field was solved unless canonical data and its disclosure say so.

## Fidelity and feature disclosure

The UI exposes manifest fidelity, `RESOLVED` / `MODELED` / `VISUAL_ONLY` / `NOT_IMPLEMENTED` feature disclosures, manifest producer/solver, topology-event provenance, optical thickness source, and the loader's `TEST_FIXTURE` source label for canonical test fixtures.

Absent optional physics remains absent/Unavailable. The viewer does not infer pressure, curvature, film thickness, surface area, solver status, or physical validity from rendered geometry. A visually convincing rainbow is therefore never evidence that drainage or a thickness field was solved.

## iPhone Safari interaction and responsive layout

The viewer uses a dedicated Pointer Events gesture state machine shared by desktop and mobile input handling. This avoids treating a camera gesture as a selection or edit.

- **Tap:** select a bubble or a canonical film surface. Tapping empty space clears selection.
- **One-finger drag:** orbit after an 8 CSS px tap-slop threshold.
- **Two-finger gesture:** pinch zoom and centroid-based pan. Once a second pointer participates, that gesture cannot become a selection/add tap.
- **Add bubble:** enter **Add bubble** explicitly, then tap the placement plane. The tap edits only the canonical editable `SCENARIO` state. Replay/`FRAME` mode rejects placement and remains read-only.
- **Focus selected / Fit all:** available as explicit buttons, so mobile use does not depend on mouse shortcuts or hover.
- **Replay:** play/pause, previous frame, next frame, reset, frame index, and exact simulation time remain visible controls. Replay continues to use exact stored frames without interpolation.

Portrait phones and short landscape viewports use a collapsible inspector drawer. Desktop-class viewports keep the side inspector. The layout uses `100dvh` / `100svh` fallbacks and `env(safe-area-inset-*)` so the notch and home indicator do not cover primary controls. Primary compact-layout buttons target at least 44 CSS px height. The canvas owns touch gestures with `touch-action: none`; scrollable inspector panels use normal touch scrolling and do not route those gestures to the camera.

## Mobile rendering-performance profiles

Rendering profiles modify presentation cost only. They never change canonical meshes, contract fields, solver outputs, feature disclosures, or provenance.

| Profile | Pixel ratio | Sphere fallback tessellation | Expensive optics |
| --- | --- | --- | --- |
| **Auto** | Up to 1.5 on coarse-pointer / phone-class viewports; up to 2 otherwise | 28×18 mobile, 36×24 desktop | Enabled |
| **Quality** | Up to 2.5 | 48×32 | Enabled |
| **Battery / performance** | Up to 1 | 20×14 | Environment map, transmission, and iridescence disabled |

The Battery / performance profile is explicitly a renderer-quality choice. Physical film thickness values and their `RESOLVED` / `MODELED` / `VISUAL_ONLY` disclosures are left untouched. If iridescence is disabled for presentation cost, the underlying optical source data remains present and is still disclosed in the inspector.

## Mobile verification boundary

`npm run test:mobile` is deterministic CI coverage for gesture arbitration, tap-vs-drag threshold, one-pointer orbit transition, two-pointer pinch/pan transition, edit gating, replay edit rejection, rendering-profile selection, DPR caps, and representative portrait/landscape layout policy.

Those tests are **not** a real Safari rendering/device test. Typecheck/build verifies browser-compatible output, but final verification on a physical iPhone Safari device is still required for WebGL driver behavior, browser-chrome resizing, thermal/performance behavior, and tactile usability.

## Known rendering limitations

- The renderer does not resolve polarization; the pure reference model averages s and p responses.
- The sampled RGB approximation is deliberately compact and is not CIE colorimetric integration.
- The built-in PMREM room environment avoids proprietary HDR assets; it is useful for reflection/refraction cues but not a measured physical illumination environment.
- Browser iridescence and transmission are rasterized approximations. Multiple nested transparent interfaces, exact internal multiple scattering, dispersion outside the thin-film model, and diffraction are not solved.
- SIDECAR thickness fields are disclosed but are not fetched by this viewer path. Only inline fields can currently drive spatially varying interference.
- A sphere fallback remains explicitly viewer-only geometry. It never becomes a canonical film mesh or a source of physical thickness.
- Modern iPhone Safari can display the WebGL viewer, but WebGL driver behavior and thermal throttling still require real-device verification. The selectable renderer profile bounds pixel ratio and presentation cost; heavy physics remains outside the phone. Fidelity/provenance rules do not change on mobile.

## Optical tests

`npm run test:optics` covers exact normal-incidence Fresnel reflectance, phase periodicity, the zero/very-small-thickness limit, incidence-angle dependence, deterministic sampled RGB, grazing-angle finite/bounded behavior, physical-vs-`VISUAL_ONLY` source classification, inline thickness-field preservation, and the absence of fabricated thickness when the contract provides none.

## Requirement traceability

This viewer advances **R2** by preserving the solver/render boundary; **R3–R5** through deterministic canonical scenario preparation and edit/review/replay separation; **R18–R20** through supported runtime/physics control mapping and truthful external handoff; **R21–R24** through explicit mesh/node/edge/normal, topology, scalar/vector, solver-diagnostic, AMR/remesh, and film-thickness observation; **R25** through transparent Fresnel/transmission, environment reflection, and thickness-driven interference; **R26–R27** through explicit film modes and topology-event lineage; **R28** through a tested gesture state machine, safe-area responsive layouts, mobile replay/edit controls, and bounded renderer-only performance profiles; **R30** through event-request and result separation; **R33** through visible provenance and feature classification; **R36** by keeping optics and runtime handoff behind canonical adapters; and **R38** by improving the integrated lab/observation layer without claiming unsolved physics.

This task does not move physics execution into the browser, add polarization, or permit renderer-driven deformation to become solver state. Canonical fixtures are contract examples, not solved validation evidence.
