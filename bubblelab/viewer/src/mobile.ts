export interface PointerPoint { x: number; y: number; }
export type GestureMode = "IDLE" | "TAP_CANDIDATE" | "ORBIT" | "PINCH_PAN" | "POST_PINCH";
export type GestureAction =
  | { type: "NONE" }
  | { type: "ORBIT"; dx: number; dy: number }
  | { type: "PINCH_PAN"; zoomFactor: number; panDx: number; panDy: number };

export interface GestureState {
  mode: GestureMode;
  pointers: ReadonlyMap<number, PointerPoint>;
  primaryId: number | null;
  startPrimary: PointerPoint | null;
  lastPrimary: PointerPoint | null;
  lastDistance: number;
  lastCentroid: PointerPoint | null;
  hadMultiTouch: boolean;
}

export interface GestureStep {
  state: GestureState;
  action: GestureAction;
  tap: PointerPoint | null;
}

export const TAP_SLOP_PX = 8;

const none = (): GestureAction => ({ type: "NONE" });
const clonePoint = (point: PointerPoint): PointerPoint => ({ x: point.x, y: point.y });
const distance = (a: PointerPoint, b: PointerPoint) => Math.hypot(a.x - b.x, a.y - b.y);
const centroid = (a: PointerPoint, b: PointerPoint): PointerPoint => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });

function firstTwo(pointers: ReadonlyMap<number, PointerPoint>): readonly [PointerPoint, PointerPoint] | null {
  const values = [...pointers.values()];
  return values.length >= 2 && values[0] && values[1] ? [values[0], values[1]] : null;
}

export function createGestureState(): GestureState {
  return {
    mode: "IDLE",
    pointers: new Map<number, PointerPoint>(),
    primaryId: null,
    startPrimary: null,
    lastPrimary: null,
    lastDistance: 0,
    lastCentroid: null,
    hadMultiTouch: false,
  };
}

export function gesturePointerDown(state: GestureState, pointerId: number, point: PointerPoint): GestureStep {
  const pointers = new Map(state.pointers);
  pointers.set(pointerId, clonePoint(point));
  if (pointers.size === 1) {
    return {
      state: {
        ...state,
        mode: "TAP_CANDIDATE",
        pointers,
        primaryId: pointerId,
        startPrimary: clonePoint(point),
        lastPrimary: clonePoint(point),
        lastDistance: 0,
        lastCentroid: null,
        hadMultiTouch: false,
      },
      action: none(),
      tap: null,
    };
  }
  const pair = firstTwo(pointers);
  if (!pair) return { state: { ...state, pointers }, action: none(), tap: null };
  return {
    state: {
      ...state,
      mode: "PINCH_PAN",
      pointers,
      lastDistance: Math.max(1, distance(pair[0], pair[1])),
      lastCentroid: centroid(pair[0], pair[1]),
      hadMultiTouch: true,
    },
    action: none(),
    tap: null,
  };
}

export function gesturePointerMove(state: GestureState, pointerId: number, point: PointerPoint): GestureStep {
  if (!state.pointers.has(pointerId)) return { state, action: none(), tap: null };
  const pointers = new Map(state.pointers);
  pointers.set(pointerId, clonePoint(point));

  if (pointers.size >= 2) {
    const pair = firstTwo(pointers);
    if (!pair) return { state: { ...state, pointers }, action: none(), tap: null };
    const nextDistance = Math.max(1, distance(pair[0], pair[1]));
    const nextCentroid = centroid(pair[0], pair[1]);
    const previousDistance = state.lastDistance > 0 ? state.lastDistance : nextDistance;
    const previousCentroid = state.lastCentroid ?? nextCentroid;
    return {
      state: {
        ...state,
        mode: "PINCH_PAN",
        pointers,
        lastDistance: nextDistance,
        lastCentroid: nextCentroid,
        hadMultiTouch: true,
      },
      action: {
        type: "PINCH_PAN",
        zoomFactor: previousDistance / nextDistance,
        panDx: nextCentroid.x - previousCentroid.x,
        panDy: nextCentroid.y - previousCentroid.y,
      },
      tap: null,
    };
  }

  if (state.mode === "POST_PINCH") {
    return {
      state: { ...state, pointers, lastPrimary: clonePoint(point) },
      action: none(),
      tap: null,
    };
  }

  const start = state.startPrimary ?? point;
  const last = state.lastPrimary ?? point;
  const moved = distance(start, point);
  if (state.mode === "TAP_CANDIDATE" && moved <= TAP_SLOP_PX) {
    return {
      state: { ...state, pointers, lastPrimary: clonePoint(point) },
      action: none(),
      tap: null,
    };
  }
  const action: GestureAction = { type: "ORBIT", dx: point.x - last.x, dy: point.y - last.y };
  return {
    state: { ...state, mode: "ORBIT", pointers, lastPrimary: clonePoint(point) },
    action,
    tap: null,
  };
}

export function gesturePointerUp(state: GestureState, pointerId: number, point: PointerPoint): GestureStep {
  if (!state.pointers.has(pointerId)) return { state, action: none(), tap: null };
  const wasSinglePointer = state.pointers.size === 1;
  const tap = wasSinglePointer
    && state.mode === "TAP_CANDIDATE"
    && !state.hadMultiTouch
    && state.startPrimary !== null
    && distance(state.startPrimary, point) <= TAP_SLOP_PX
    ? clonePoint(point)
    : null;

  const pointers = new Map(state.pointers);
  pointers.delete(pointerId);
  if (pointers.size === 0) {
    return { state: createGestureState(), action: none(), tap };
  }

  const remaining = [...pointers.entries()][0];
  if (!remaining) return { state: createGestureState(), action: none(), tap: null };
  return {
    state: {
      ...state,
      mode: "POST_PINCH",
      pointers,
      primaryId: remaining[0],
      startPrimary: clonePoint(remaining[1]),
      lastPrimary: clonePoint(remaining[1]),
      lastDistance: 0,
      lastCentroid: null,
      hadMultiTouch: true,
    },
    action: none(),
    tap: null,
  };
}

export function gesturePointerCancel(state: GestureState, pointerId: number): GestureState {
  if (!state.pointers.has(pointerId)) return state;
  const pointers = new Map(state.pointers);
  pointers.delete(pointerId);
  if (pointers.size === 0) return createGestureState();
  const remaining = [...pointers.entries()][0];
  if (!remaining) return createGestureState();
  return {
    ...state,
    mode: "POST_PINCH",
    pointers,
    primaryId: remaining[0],
    startPrimary: clonePoint(remaining[1]),
    lastPrimary: clonePoint(remaining[1]),
    lastDistance: 0,
    lastCentroid: null,
    hadMultiTouch: true,
  };
}

export function isTapWithinThreshold(start: PointerPoint, end: PointerPoint, thresholdPx = TAP_SLOP_PX): boolean {
  return distance(start, end) <= thresholdPx;
}

export function canCommitPlacementTap(mode: "EDIT" | "REPLAY", addMode: boolean, isTap: boolean): boolean {
  return mode === "EDIT" && addMode && isTap;
}

export type RenderQualityMode = "AUTO" | "QUALITY" | "BATTERY";
export interface RenderingPolicy {
  mode: RenderQualityMode;
  targetPixelRatio: number;
  sphereWidthSegments: number;
  sphereHeightSegments: number;
  expensiveOptics: boolean;
}

export function selectRenderingPolicy(
  mode: RenderQualityMode,
  viewportWidth: number,
  viewportHeight: number,
  devicePixelRatio: number,
  coarsePointer = false,
): RenderingPolicy {
  const dpr = Number.isFinite(devicePixelRatio) && devicePixelRatio > 0 ? devicePixelRatio : 1;
  if (mode === "QUALITY") {
    return { mode, targetPixelRatio: Math.min(dpr, 2.5), sphereWidthSegments: 48, sphereHeightSegments: 32, expensiveOptics: true };
  }
  if (mode === "BATTERY") {
    return { mode, targetPixelRatio: Math.min(dpr, 1), sphereWidthSegments: 20, sphereHeightSegments: 14, expensiveOptics: false };
  }
  const mobileClass = coarsePointer || viewportWidth <= 760 || viewportHeight <= 500;
  return mobileClass
    ? { mode, targetPixelRatio: Math.min(dpr, 1.5), sphereWidthSegments: 28, sphereHeightSegments: 18, expensiveOptics: true }
    : { mode, targetPixelRatio: Math.min(dpr, 2), sphereWidthSegments: 36, sphereHeightSegments: 24, expensiveOptics: true };
}

export interface LayoutPolicy {
  orientation: "PORTRAIT" | "LANDSCAPE";
  inspector: "DRAWER" | "SIDEBAR";
  compact: boolean;
}

export function selectLayoutPolicy(viewportWidth: number, viewportHeight: number): LayoutPolicy {
  const orientation = viewportHeight >= viewportWidth ? "PORTRAIT" : "LANDSCAPE";
  const compact = viewportWidth <= 760 || viewportHeight <= 500;
  return { orientation, inspector: compact ? "DRAWER" : "SIDEBAR", compact };
}
