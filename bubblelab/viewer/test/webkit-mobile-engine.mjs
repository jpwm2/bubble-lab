import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { dirname, extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { webkit } from "playwright";

const here = dirname(fileURLToPath(import.meta.url));
const viewerDir = resolve(here, "..");
const distDir = join(viewerDir, "dist");
const replayFixtureDir = join(here, "fixtures", "webkit-replay");
const resultDir = join(viewerDir, "test-results");
const profiles = [
  { name: "iphone-class-390x844", width: 390, height: 844, dpr: 3 },
  { name: "iphone-class-844x390-landscape", width: 844, height: 390, dpr: 3 },
  { name: "iphone-class-430x932", width: 430, height: 932, dpr: 3 },
];
const mime = new Map([
  [".html", "text/html; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".css", "text/css; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
]);
const ok = (condition, message) => assert.ok(condition, message);

async function serveDist() {
  const server = createServer(async (request, response) => {
    try {
      const pathname = decodeURIComponent(new URL(request.url ?? "/", "http://127.0.0.1").pathname);
      const relative = pathname === "/" ? "index.html" : pathname.replace(/^\/+/, "");
      const target = resolve(distDir, relative);
      if (target !== distDir && !target.startsWith(`${distDir}${sep}`)) throw new Error("outside dist");
      if (!(await stat(target)).isFile()) throw new Error("not a file");
      response.writeHead(200, { "content-type": mime.get(extname(target)) ?? "application/octet-stream", "cache-control": "no-store" });
      response.end(await readFile(target));
    } catch {
      response.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
      response.end("not found");
    }
  });
  await new Promise((resolveListen, rejectListen) => {
    server.once("error", rejectListen);
    server.listen(0, "127.0.0.1", resolveListen);
  });
  const address = server.address();
  ok(address && typeof address === "object", "static server did not expose a port");
  return {
    origin: `http://127.0.0.1:${address.port}`,
    close: () => new Promise((resolveClose, rejectClose) => server.close((error) => error ? rejectClose(error) : resolveClose())),
  };
}

async function waitForReady(page) {
  await page.waitForFunction(() => {
    const status = document.querySelector("#status-line")?.textContent ?? "";
    const canvas = document.querySelector("#viewport");
    const backend = document.querySelector("#lab-backend");
    const rect = canvas?.getBoundingClientRect();
    return Boolean(
      status && !status.startsWith("Loading") && !status.includes("Viewer startup failed")
      && canvas instanceof HTMLCanvasElement
      && backend instanceof HTMLSelectElement
      && rect && rect.width > 0 && rect.height > 0
    );
  }, null, { timeout: 20_000 });
}

async function environment(page) {
  return page.evaluate(() => {
    const canvas = document.querySelector("#viewport");
    const rect = canvas?.getBoundingClientRect();
    return {
      viewport: { width: innerWidth, height: innerHeight },
      userAgent: navigator.userAgent,
      devicePixelRatio,
      maxTouchPoints: navigator.maxTouchPoints,
      touchEventSurface: "ontouchstart" in window,
      coarsePointer: matchMedia("(pointer: coarse)").matches,
      anyCoarsePointer: matchMedia("(any-pointer: coarse)").matches,
      webgl: Boolean(document.createElement("canvas").getContext("webgl")),
      webgl2: Boolean(document.createElement("canvas").getContext("webgl2")),
      canvas: rect ? { width: rect.width, height: rect.height } : null,
      inspectorLayout: document.documentElement.dataset.inspectorLayout ?? null,
      orientation: document.documentElement.dataset.orientation ?? null,
    };
  });
}

async function touchBox(page, selector, label) {
  const locator = page.locator(selector);
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  ok(box, `${label}: missing browser layout box`);
  ok(box.width >= 43.25 && box.height >= 43.25, `${label}: expected 44px-class target, got ${box.width}x${box.height}`);
  return { width: box.width, height: box.height };
}

async function verifyResponsiveShell(page, profile) {
  const env = await environment(page);
  assert.deepEqual(env.viewport, { width: profile.width, height: profile.height }, `${profile.name}: effective viewport mismatch`);
  assert.equal(env.devicePixelRatio, profile.dpr, `${profile.name}: DPR mismatch`);
  ok(env.canvas && env.canvas.width > 0 && env.canvas.height > 0, `${profile.name}: 3D canvas has no size`);
  ok(env.webgl || env.webgl2, `${profile.name}: WebGL unavailable in WebKit process`);
  ok(env.touchEventSurface || env.maxTouchPoints > 0, `${profile.name}: touch surface unavailable in WebKit context`);
  assert.equal(env.inspectorLayout, "drawer", `${profile.name}: compact drawer layout not selected`);
  assert.equal(env.orientation, profile.width > profile.height ? "landscape" : "portrait", `${profile.name}: orientation policy mismatch`);

  const overflow = await page.evaluate(() => ({
    viewport: innerWidth,
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }));
  ok(Math.max(overflow.document, overflow.body) <= overflow.viewport + 2, `${profile.name}: horizontal document overflow ${JSON.stringify(overflow)}`);

  const toggle = page.locator("#inspector-toggle");
  await toggle.tap();
  assert.equal(await toggle.getAttribute("aria-expanded"), "true", `${profile.name}: Inspector did not open from touch tap`);
  ok(await page.locator("#inspector-panel").isVisible(), `${profile.name}: Inspector not visible after open`);
  await toggle.tap();
  assert.equal(await toggle.getAttribute("aria-expanded"), "false", `${profile.name}: Inspector did not close from touch tap`);

  const toolbar = page.locator(".viewport-overlay > .toolbar");
  const toolbarMetrics = await toolbar.evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
    touchAction: getComputedStyle(element).touchAction,
  }));
  ok(toolbarMetrics.scrollWidth > toolbarMetrics.clientWidth, `${profile.name}: toolbar is not horizontally scrollable`);
  ok(toolbarMetrics.touchAction.includes("pan-x"), `${profile.name}: toolbar does not expose pan-x`);
  await toolbar.evaluate((element) => { element.scrollLeft = element.scrollWidth; });
  const terminal = await page.evaluate(() => {
    const toolbarElement = document.querySelector(".viewport-overlay > .toolbar");
    const last = document.querySelector("#fit-all");
    if (!(toolbarElement instanceof HTMLElement) || !(last instanceof HTMLElement)) return null;
    const a = toolbarElement.getBoundingClientRect();
    const b = last.getBoundingClientRect();
    return { left: a.left, right: a.right, itemLeft: b.left, itemRight: b.right, scrollLeft: toolbarElement.scrollLeft };
  });
  ok(terminal && terminal.scrollLeft > 0 && terminal.itemLeft >= terminal.left - 2 && terminal.itemRight <= terminal.right + 2,
    `${profile.name}: terminal toolbar control not reachable by horizontal scrolling`);
  await toolbar.evaluate((element) => { element.scrollLeft = 0; });

  const targets = {
    inspector: await touchBox(page, "#inspector-toggle", `${profile.name} Inspector`),
    replayForward: await touchBox(page, "#replay-forward", `${profile.name} Replay forward`),
  };
  return { env, overflow, toolbarMetrics, targets };
}

async function verifyInspectorAndScenario(page, profile) {
  const profileName = profile.name;
  const toggle = page.locator("#inspector-toggle");
  if (await toggle.getAttribute("aria-expanded") !== "true") await toggle.tap();
  const panel = page.locator("#inspector-panel");
  const scroll = await panel.evaluate((element) => ({
    clientHeight: element.clientHeight,
    scrollHeight: element.scrollHeight,
    touchAction: getComputedStyle(element).touchAction,
    before: element.scrollTop,
  }));
  ok(scroll.scrollHeight > scroll.clientHeight, `${profileName}: Inspector is not a scroll container`);
  ok(scroll.touchAction.includes("pan-y"), `${profileName}: Inspector does not expose pan-y`);
  await panel.evaluate((element) => { element.scrollTop = Math.min(480, element.scrollHeight - element.clientHeight); });
  const isolation = await page.evaluate(() => ({
    inspectorScrollTop: document.querySelector("#inspector-panel")?.scrollTop ?? 0,
    inspectorOverflowY: getComputedStyle(document.querySelector("#inspector-panel")).overflowY,
    canvasTouchAction: getComputedStyle(document.querySelector("#viewport")).touchAction,
  }));
  ok(isolation.inspectorScrollTop > scroll.before, `${profileName}: WebKit did not scroll the Inspector container`);
  ok(["auto", "scroll"].includes(isolation.inspectorOverflowY), `${profileName}: Inspector overflow-y is not scrollable`);
  assert.equal(isolation.canvasTouchAction, "none", `${profileName}: canvas must own 3D gesture stream`);

  const cadence = page.locator("#lab-cadence");
  await cadence.scrollIntoViewIfNeeded();
  await cadence.fill("0.025");
  assert.equal(await cadence.inputValue(), "0.025", `${profileName}: cadence field did not accept input`);
  await page.locator("#lab-backend").selectOption("equilibrium");
  assert.equal(await page.locator("#lab-backend").inputValue(), "equilibrium", `${profileName}: backend selector failed`);
  await page.locator("#lab-backend").selectOption("transient");
  await page.locator("#lab-fidelity").selectOption("MAXIMUM_REALISM");
  assert.equal(await page.locator("#lab-fidelity").inputValue(), "MAXIMUM_REALISM", `${profileName}: fidelity selector failed`);

  const add = page.locator("#lab-add-boundary");
  await add.scrollIntoViewIfNeeded();
  await page.locator("#lab-boundary-add-type").selectOption("floor");
  const before = await page.locator("[data-boundary-editor]").count();
  await add.tap();
  await page.waitForFunction((count) => document.querySelectorAll("[data-boundary-editor]").length > count, before);
  const editor = page.locator("[data-boundary-editor]").last();
  await editor.scrollIntoViewIfNeeded();
  const box = await editor.boundingBox();
  ok(box && box.width > 0 && box.x >= -2 && box.x + box.width <= profile.width + 2, `${profileName}: boundary editor not reachable in viewport`);
  const addTarget = await touchBox(page, "#lab-add-boundary", `${profileName} Add boundary`);
  return { scroll, isolation, addTarget };
}

async function verifyPointerPaths(page, profileName) {
  const toggle = page.locator("#inspector-toggle");
  if (await toggle.getAttribute("aria-expanded") === "true") await toggle.tap();
  const canvas = page.locator("#viewport");
  const box = await canvas.boundingBox();
  ok(box && box.width > 120 && box.height > 120, `${profileName}: canvas too small for pointer checks`);
  const center = { x: box.x + box.width / 2, y: box.y + box.height / 2 };

  await page.touchscreen.tap(center.x, center.y);
  await page.waitForFunction(() => !(document.querySelector("#selection-panel")?.textContent ?? "").includes("No bubble"), null, { timeout: 5000 });
  const selected = (await page.locator("#selection-panel").textContent()) ?? "";
  ok(!selected.includes("No bubble"), `${profileName}: automated touch tap did not select centered bubble`);

  const complex = await page.evaluate(() => {
    const canvasElement = document.querySelector("#viewport");
    const selection = document.querySelector("#selection-panel");
    if (!(canvasElement instanceof HTMLCanvasElement) || !(selection instanceof HTMLElement)) throw new Error("pointer targets unavailable");
    const rect = canvasElement.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const original = {
      set: canvasElement.setPointerCapture,
      release: canvasElement.releasePointerCapture,
      has: canvasElement.hasPointerCapture,
    };
    Object.defineProperty(canvasElement, "setPointerCapture", { configurable: true, value: () => {} });
    Object.defineProperty(canvasElement, "releasePointerCapture", { configurable: true, value: () => {} });
    Object.defineProperty(canvasElement, "hasPointerCapture", { configurable: true, value: () => false });
    let mutations = 0;
    const observer = new MutationObserver(() => { mutations += 1; });
    observer.observe(selection, { subtree: true, childList: true, characterData: true });
    const baseline = selection.textContent;
    const fire = (type, pointerId, x, y, isPrimary) => canvasElement.dispatchEvent(new PointerEvent(type, {
      bubbles: true, cancelable: true, pointerId, pointerType: "touch", isPrimary,
      clientX: x, clientY: y, buttons: type === "pointerup" ? 0 : 1,
    }));
    try {
      fire("pointerdown", 71, cx - 22, cy, true);
      fire("pointerdown", 72, cx + 22, cy, false);
      fire("pointermove", 71, cx - 38, cy + 2, true);
      fire("pointermove", 72, cx + 38, cy - 2, false);
      fire("pointerup", 72, cx + 38, cy - 2, false);
      fire("pointermove", 71, rect.right - 18, cy + 70, true);
      fire("pointerup", 71, rect.right - 18, cy + 70, true);
      return { baseline, after: selection.textContent, mutations };
    } finally {
      observer.disconnect();
      Object.defineProperty(canvasElement, "setPointerCapture", { configurable: true, value: original.set.bind(canvasElement) });
      Object.defineProperty(canvasElement, "releasePointerCapture", { configurable: true, value: original.release.bind(canvasElement) });
      Object.defineProperty(canvasElement, "hasPointerCapture", { configurable: true, value: original.has.bind(canvasElement) });
    }
  });
  assert.equal(complex.after, complex.baseline, `${profileName}: post-pinch remaining pointer caused accidental selection`);
  assert.equal(complex.mutations, 0, `${profileName}: post-pinch path mutated selection`);
  return { selected: selected.replace(/\s+/g, " ").trim(), complex };
}

async function verifyReplay(page, profileName) {
  await page.locator("#runtime-bundle-input").setInputFiles(replayFixtureDir);
  await page.waitForFunction(() => {
    const mode = document.querySelector("#mode-replay")?.getAttribute("aria-pressed");
    const position = document.querySelector("#replay-position")?.textContent ?? "";
    return mode === "true" && position.includes("1/2") && position.includes("t=0.000000 s");
  }, null, { timeout: 15_000 });
  ok(await page.locator("#add-toggle").isDisabled(), `${profileName}: replay left add mutation enabled`);
  ok(await page.locator("#delete-selected").isDisabled(), `${profileName}: replay left delete mutation enabled`);
  ok(await page.locator("#burst-request").isDisabled(), `${profileName}: replay left burst mutation enabled`);

  const status = (await page.locator("#status-line").textContent()) ?? "";
  const provenance = (await page.locator("#provenance-panel").textContent()) ?? "";
  ok(status.includes("Runtime bundle: webkit-mobile-test / fixture-generator 1.0-test"), `${profileName}: runtime bundle did not use UI load path`);
  ok(status.includes("read-only"), `${profileName}: replay status missing read-only disclosure`);
  ok(provenance.includes("TEST_FIXTURE WebKit mobile browser verification"), `${profileName}: TEST_FIXTURE provenance missing`);
  ok(provenance.includes("fixture-generator 1.0-test"), `${profileName}: solver/backend provenance missing`);
  ok(provenance.includes("surface_geometry"), `${profileName}: feature disclosures missing`);

  await page.locator("#replay-forward").click();
  await page.waitForFunction(() => (document.querySelector("#replay-position")?.textContent ?? "").includes("2/2"));
  await page.locator("#replay-back").click();
  await page.waitForFunction(() => (document.querySelector("#replay-position")?.textContent ?? "").includes("1/2"));
  const play = page.locator("#replay-play");
  await play.click();
  assert.equal((await play.textContent())?.trim(), "Pause", `${profileName}: replay Play failed`);
  await play.click();
  assert.equal((await play.textContent())?.trim(), "Play", `${profileName}: replay Pause failed`);
  return { status: status.trim(), provenance: provenance.replace(/\s+/g, " ").trim() };
}

async function runProfile(browser, browserVersion, origin, profile, full) {
  const context = await browser.newContext({
    viewport: { width: profile.width, height: profile.height },
    screen: { width: profile.width, height: profile.height },
    deviceScaleFactor: profile.dpr,
    isMobile: true,
    hasTouch: true,
  });
  const page = await context.newPage();
  const pageErrors = [];
  const consoleErrors = [];
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  try {
    await page.goto(origin, { waitUntil: "load", timeout: 30_000 });
    await waitForReady(page);
    const shell = await verifyResponsiveShell(page, profile);
    const inspectorScenario = full ? await verifyInspectorAndScenario(page, profile) : null;
    const pointers = full ? await verifyPointerPaths(page, profile.name) : null;
    const replay = full ? await verifyReplay(page, profile.name) : null;
    assert.equal(pageErrors.length, 0, `${profile.name}: uncaught page errors: ${pageErrors.join(" | ")}`);
    return { profile, browserVersion, ...shell, inspectorScenario, pointers, replay, pageErrors, consoleErrors };
  } finally {
    await context.close();
  }
}

await stat(join(distDir, "index.html"));
await stat(join(replayFixtureDir, "replay.json"));
await mkdir(resultDir, { recursive: true });
const server = await serveDist();
const browser = await webkit.launch({ headless: true });
const browserVersion = browser.version();
const results = [];
try {
  for (const [index, profile] of profiles.entries()) results.push(await runProfile(browser, browserVersion, server.origin, profile, index === 0));
} finally {
  await browser.close();
  await server.close();
}
const evidence = {
  engine: "Playwright WebKit",
  browserVersion,
  identityPolicy: "No Safari/iPhone user-agent override; userAgent is the WebKit process default.",
  nativeMultiTouchClaim: "UNVERIFIED. Native two-finger hardware touch is not synthesized; the post-pinch path uses PointerEvent dispatch through live canvas listeners.",
  physicalIPhoneSafariClaim: "UNVERIFIED. This is CI WebKit-engine evidence, not physical iPhone Safari certification.",
  results,
};
await writeFile(join(resultDir, "webkit-mobile-observations.json"), `${JSON.stringify(evidence, null, 2)}\n`, "utf8");
console.log(`[webkit-mobile] ${JSON.stringify(evidence, null, 2)}`);
console.log(`[webkit-mobile] PASS: ${profiles.length} iPhone-class profiles exercised in a real WebKit process`);
