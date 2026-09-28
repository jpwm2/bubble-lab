import * as THREE from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import {
  deterministicSampleIndices,
  discoverScalarFields,
  discoverVectorFields,
  normalizedScalar,
  resolveScalarRange,
  type ScalarFieldDescriptor,
  type ScalarRange,
  type VectorFieldDescriptor,
} from "./debug.js";
import {
  AIR_IOR, SOAP_FILM_IOR, featureFilmThicknessStatus, resolveOpticalThickness, thinFilmRgb,
  type InterferenceMode, type OpticalThicknessDecision, type PhysicalThicknessCandidate,
} from "./optics.js";
import {
  createGestureState,
  gesturePointerCancel,
  gesturePointerDown,
  gesturePointerMove,
  gesturePointerUp,
  selectRenderingPolicy,
  type RenderQualityMode,
} from "./mobile.js";
import type { JunctionDescriptor, RenderBubble, RenderSceneData, RenderSurfaceMesh, Vec3 } from "./types.js";

export type FilmVisibilityMode = "ALL" | "OUTER" | "SHARED" | "NONE";
export interface DisplayOptions {
  filmMode: FilmVisibilityMode;
  showCanonicalMesh: boolean;
  showSphereFallback: boolean;
  showFaces: boolean;
  wireframe: boolean;
  showVertices: boolean;
  showVertexNormals: boolean;
  showFaceNormals: boolean;
  showJunctions: boolean;
  scalarChannel: string;
  scalarRangeMode: "AUTO" | "MANUAL";
  scalarMin: number | null;
  scalarMax: number | null;
  scalarDiverging: boolean;
  vectorChannel: string;
  vectorGlyphCount: number;
  vectorScale: number;
  vectorNormalize: boolean;
  interferenceMode: InterferenceMode;
  visualPreviewThicknessNm: number;
  qualityMode: RenderQualityMode;
}
export interface SceneInteractionCallbacks {
  onCameraGesture?: () => void;
  onTap?: (clientX: number, clientY: number, additive: boolean) => void;
}
export type PickTarget =
  | { kind: "BUBBLE"; id: string }
  | { kind: "SURFACE"; id: string; ownerBubbleIds: readonly string[] }
  | { kind: "JUNCTION"; id: string };
export interface SceneController {
  camera: any; renderer: any; canvas: HTMLCanvasElement;
  setData(data: RenderSceneData, selectedIds: Set<string>, selectedSurfaceId: string | null, options: DisplayOptions): void;
  setCamera(target: Vec3, distance: number): void;
  projectToPlacementPlane(clientX: number, clientY: number): Vec3 | null;
  pickTarget(clientX: number, clientY: number): PickTarget | null;
  dispose(): void;
}

interface CachedSurfaceGeometry {
  geometry: any;
  thicknessTexture?: any;
}

function scalarValue(channel: string, physical: RenderSceneData["bubbles"][number]["physical"]): number | null | undefined {
  if (channel === "pressure" || channel === "bubble:pressure_pa") return physical.pressure;
  if (channel === "curvature" || channel === "bubble:mean_curvature_m_inv") return physical.curvature;
  if (channel === "thickness" || channel === "bubble:film_thickness_m") return physical.thickness;
  if (channel === "volumeError" || channel === "bubble:relative_volume_error") return physical.volumeError;
  if (channel === "bubble:volume_m3") return physical.volume;
  if (channel === "bubble:equivalent_radius_m") return physical.equivalentRadius;
  if (channel === "bubble:surface_area_m2") return physical.area;
  return undefined;
}
function filmVisible(role: RenderSurfaceMesh["geometryRole"], mode: FilmVisibilityMode): boolean {
  if (role !== "OUTER_FILM" && role !== "SHARED_FILM") return true;
  if (mode === "NONE") return false;
  if (mode === "OUTER") return role === "OUTER_FILM";
  if (mode === "SHARED") return role === "SHARED_FILM";
  return true;
}
function candidateFromSurface(surface: RenderSurfaceMesh): PhysicalThicknessCandidate | undefined {
  const thickness = surface.physicalThickness;
  if (!thickness) return undefined;
  if (thickness.kind === "SCALAR" && typeof thickness.scalarM === "number") {
    const result: PhysicalThicknessCandidate = { kind: "SCALAR", scalarM: thickness.scalarM };
    if (thickness.fieldName) result.fieldName = thickness.fieldName;
    return result;
  }
  if (thickness.valuesM) {
    const result: PhysicalThicknessCandidate = { kind: thickness.kind, valuesM: thickness.valuesM };
    if (thickness.fieldName) result.fieldName = thickness.fieldName;
    return result;
  }
  return undefined;
}
function candidateFromBubble(bubble: RenderBubble): PhysicalThicknessCandidate | undefined {
  const value = bubble.physical.thickness;
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? { kind: "SCALAR", scalarM: value } : undefined;
}
function decisionRepresentativeThickness(decision: OpticalThicknessDecision): number | undefined {
  if (typeof decision.thicknessM === "number") return decision.thicknessM;
  if (!decision.fieldValuesM?.length) return undefined;
  return decision.fieldValuesM.reduce((sum, value) => sum + value, 0) / decision.fieldValuesM.length;
}
function decisionRangeNm(decision: OpticalThicknessDecision): readonly [number, number] | undefined {
  if (typeof decision.thicknessM === "number") {
    const nm = Math.max(0, decision.thicknessM * 1e9);
    return [nm, nm];
  }
  if (!decision.fieldValuesM?.length) return undefined;
  let min = Infinity, max = -Infinity;
  for (const value of decision.fieldValuesM) {
    if (!Number.isFinite(value) || value < 0) continue;
    const nm = value * 1e9;
    min = Math.min(min, nm); max = Math.max(max, nm);
  }
  return Number.isFinite(min) && Number.isFinite(max) ? [min, max] : undefined;
}
function normalizedThickness(valueM: number, rangeNm: readonly [number, number]): number {
  const valueNm = valueM * 1e9, span = rangeNm[1] - rangeNm[0];
  return span <= 1e-12 ? 1 : Math.min(1, Math.max(0, (valueNm - rangeNm[0]) / span));
}
function createThicknessGradientTexture(): any {
  const data = new Uint8Array(256 * 4);
  for (let i = 0; i < 256; i += 1) {
    const offset = i * 4;
    data[offset] = 255; data[offset + 1] = i; data[offset + 2] = 255; data[offset + 3] = 255;
  }
  const texture = new THREE.DataTexture(data, 256, 1, THREE.RGBAFormat);
  texture.needsUpdate = true;
  texture.minFilter = THREE.LinearFilter; texture.magFilter = THREE.LinearFilter;
  texture.wrapS = THREE.ClampToEdgeWrapping; texture.wrapT = THREE.ClampToEdgeWrapping;
  return texture;
}
function buildSurfaceGeometry(surface: RenderSurfaceMesh, decision: OpticalThicknessDecision): CachedSurfaceGeometry {
  const geometry = new THREE.BufferGeometry();
  if (!surface.vertices || !surface.faces) return { geometry };
  const rangeNm = decisionRangeNm(decision), field = decision.fieldValuesM;
  if (field && rangeNm && decision.fieldAssociation === "FACE" && field.length === surface.faces.length) {
    const positions: number[] = [], uvs: number[] = [];
    for (let faceIndex = 0; faceIndex < surface.faces.length; faceIndex += 1) {
      const face = surface.faces[faceIndex], thicknessM = field[faceIndex];
      if (!face || thicknessM === undefined) continue;
      const u = normalizedThickness(thicknessM, rangeNm);
      for (const vertexIndex of face) {
        const vertex = surface.vertices[vertexIndex];
        if (!vertex) continue;
        positions.push(...vertex); uvs.push(u, 0.5);
      }
    }
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    geometry.setAttribute("uv", new THREE.Float32BufferAttribute(uvs, 2));
    geometry.computeVertexNormals();
    return { geometry, thicknessTexture: createThicknessGradientTexture() };
  }
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(surface.vertices.flatMap((value) => [...value]), 3));
  geometry.setIndex(surface.faces.flatMap((value) => [...value]));
  if (field && rangeNm && decision.fieldAssociation === "VERTEX" && field.length === surface.vertices.length) {
    const uvs = field.flatMap((value) => [normalizedThickness(value, rangeNm), 0.5]);
    geometry.setAttribute("uv", new THREE.Float32BufferAttribute(uvs, 2));
    geometry.computeVertexNormals();
    return { geometry, thicknessTexture: createThicknessGradientTexture() };
  }
  geometry.computeVertexNormals();
  return { geometry };
}
function opticalMaterial(
  decision: OpticalThicknessDecision,
  selected: boolean,
  shared: boolean,
  thicknessTexture?: any,
  expensiveOptics = true,
): any {
  const activeInterference = decision.source !== "NONE" && decision.source !== "BLOCKED_BY_DISCLOSURE";
  const representative = decisionRepresentativeThickness(decision);
  const rgb = activeInterference && representative !== undefined ? thinFilmRgb(representative, 0.65, SOAP_FILM_IOR) : undefined;
  const color = rgb
    ? new THREE.Color(0.34 + rgb[0] * 0.66, 0.34 + rgb[1] * 0.66, 0.34 + rgb[2] * 0.66)
    : new THREE.Color(shared ? 0x9be7f2 : 0xd3efff);
  const material = new THREE.MeshPhysicalMaterial({
    color, roughness: expensiveOptics ? 0.025 : 0.12, metalness: 0, transmission: expensiveOptics ? 0.94 : 0, transparent: true,
    opacity: selected ? 0.78 : shared ? 0.5 : 0.42, thickness: 0, ior: SOAP_FILM_IOR,
    clearcoat: expensiveOptics ? 0.18 : 0.04, clearcoatRoughness: expensiveOptics ? 0.04 : 0.16, side: THREE.DoubleSide, depthWrite: false,
    emissive: selected ? (shared ? 0x073b44 : 0x18354d) : 0x000000, emissiveIntensity: selected ? 0.55 : 0,
    iridescence: activeInterference && expensiveOptics ? 1 : 0, iridescenceIOR: SOAP_FILM_IOR,
  });
  const rangeNm = decisionRangeNm(decision);
  if (activeInterference && rangeNm) {
    material.iridescenceThicknessRange = [...rangeNm];
    if (thicknessTexture) material.iridescenceThicknessMap = thicknessTexture;
  }
  return material;
}
function addWireOverlay(root: any, geometry: any, shared: boolean) {
  const edges = new THREE.EdgesGeometry(geometry);
  const lines = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: shared ? 0x22d3ee : 0xb6ddff, transparent: true, opacity: 0.62 }));
  lines.renderOrder = 4;
  root.add(lines);
}
function surfaceScale(surface: RenderSurfaceMesh): number {
  if (!surface.vertices?.length) return 0.001;
  let minX = Infinity, minY = Infinity, minZ = Infinity, maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity;
  for (const [x, y, z] of surface.vertices) {
    minX = Math.min(minX, x); minY = Math.min(minY, y); minZ = Math.min(minZ, z);
    maxX = Math.max(maxX, x); maxY = Math.max(maxY, y); maxZ = Math.max(maxZ, z);
  }
  return Math.max(1e-7, Math.max(maxX - minX, maxY - minY, maxZ - minZ));
}
function scalarRgb(value: number, range: ScalarRange): readonly [number, number, number] {
  const t = normalizedScalar(value, range);
  if (t === undefined) return [0.35, 0.35, 0.4];
  if (!range.diverging) {
    const color = new THREE.Color().setHSL((1 - t) * 0.66, 0.85, 0.52);
    return [color.r, color.g, color.b];
  }
  if (t <= 0.5) {
    const local = t * 2;
    return [0.18 + local * 0.82, 0.35 + local * 0.65, 0.95];
  }
  const local = (t - 0.5) * 2;
  return [1, 1 - local * 0.78, 1 - local * 0.78];
}
function scalarGeometry(surface: RenderSurfaceMesh, field: ScalarFieldDescriptor, range: ScalarRange): any | undefined {
  if (!surface.vertices || !surface.faces || field.meshId !== surface.id) return undefined;
  const geometry = new THREE.BufferGeometry();
  if (field.association === "VERTEX" && field.values.length === surface.vertices.length) {
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(surface.vertices.flatMap((value) => [...value]), 3));
    geometry.setIndex(surface.faces.flatMap((value) => [...value]));
    geometry.setAttribute("color", new THREE.Float32BufferAttribute(field.values.flatMap((value) => [...scalarRgb(value, range)]), 3));
    return geometry;
  }
  if (field.association === "FACE" && field.values.length === surface.faces.length) {
    const positions: number[] = [], colors: number[] = [];
    surface.faces.forEach((face, faceIndex) => {
      const value = field.values[faceIndex];
      if (value === undefined) return;
      const rgb = scalarRgb(value, range);
      for (const vertexIndex of face) {
        const vertex = surface.vertices?.[vertexIndex];
        if (!vertex) continue;
        positions.push(...vertex); colors.push(...rgb);
      }
    });
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
    return geometry;
  }
  geometry.dispose();
  return undefined;
}
function mappedEntityScalar(
  data: RenderSceneData,
  surface: RenderSurfaceMesh,
  field: ScalarFieldDescriptor,
): number | undefined {
  if (!data.frame) return undefined;
  if (field.association === "FILM" && surface.filmId && field.values.length === data.frame.film_regions.length) {
    const index = data.frame.film_regions.findIndex((film) => film.id === surface.filmId);
    const value = index >= 0 ? field.values[index] : undefined;
    return typeof value === "number" && Number.isFinite(value) ? value : undefined;
  }
  if (field.association === "BUBBLE" && surface.ownerBubbleIds.length === 1 && field.values.length === data.frame.bubbles.length) {
    const owner = surface.ownerBubbleIds[0];
    const index = data.frame.bubbles.findIndex((bubble) => bubble.id === owner);
    const value = index >= 0 ? field.values[index] : undefined;
    return typeof value === "number" && Number.isFinite(value) ? value : undefined;
  }
  return undefined;
}
function addScalarOverlay(
  root: any,
  surface: RenderSurfaceMesh,
  field: ScalarFieldDescriptor | undefined,
  range: ScalarRange | undefined,
  data: RenderSceneData,
  cachedGeometry: any,
) {
  if (!field || !field.available || !range) return;
  const geometry = scalarGeometry(surface, field, range);
  if (geometry) {
    const material = new THREE.MeshBasicMaterial({
      vertexColors: true, transparent: true, opacity: 0.74, side: THREE.DoubleSide, depthWrite: false,
      polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1,
    });
    const overlay = new THREE.Mesh(geometry, material);
    overlay.renderOrder = 5;
    root.add(overlay);
    return;
  }
  const mapped = mappedEntityScalar(data, surface, field);
  if (mapped === undefined) return;
  const rgb = scalarRgb(mapped, range);
  const material = new THREE.MeshBasicMaterial({
    color: new THREE.Color(rgb[0], rgb[1], rgb[2]),
    transparent: true, opacity: 0.74, side: THREE.DoubleSide, depthWrite: false,
    polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1,
  });
  const overlay = new THREE.Mesh(cachedGeometry, material);
  overlay.userData.cachedGeometry = true;
  overlay.renderOrder = 5;
  root.add(overlay);
}
function addVertexPoints(root: any, surface: RenderSurfaceMesh) {
  if (!surface.vertices?.length) return;
  const indices = deterministicSampleIndices(surface.vertices.length, 2500);
  const positions = indices.flatMap((index) => surface.vertices?.[index] ? [...surface.vertices[index]!] : []);
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  root.add(new THREE.Points(geometry, new THREE.PointsMaterial({ size: 4, sizeAttenuation: false, color: 0xf8fafc })));
}
function faceCentroid(surface: RenderSurfaceMesh, faceIndex: number): Vec3 | undefined {
  const face = surface.faces?.[faceIndex];
  if (!face || !surface.vertices) return undefined;
  const a = surface.vertices[face[0]], b = surface.vertices[face[1]], c = surface.vertices[face[2]];
  if (!a || !b || !c) return undefined;
  return [(a[0] + b[0] + c[0]) / 3, (a[1] + b[1] + c[1]) / 3, (a[2] + b[2] + c[2]) / 3];
}
function faceNormal(surface: RenderSurfaceMesh, faceIndex: number): Vec3 | undefined {
  const face = surface.faces?.[faceIndex];
  if (!face || !surface.vertices) return undefined;
  const a = surface.vertices[face[0]], b = surface.vertices[face[1]], c = surface.vertices[face[2]];
  if (!a || !b || !c) return undefined;
  const ab = new THREE.Vector3(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
  const ac = new THREE.Vector3(c[0] - a[0], c[1] - a[1], c[2] - a[2]);
  const normal = ab.cross(ac);
  if (normal.lengthSq() <= 1e-30) return [0, 0, 0];
  normal.normalize();
  return [normal.x, normal.y, normal.z];
}
function addLineVectors(
  root: any,
  anchors: readonly Vec3[],
  vectors: readonly Vec3[],
  indices: readonly number[],
  lengthScale: number,
  normalize: boolean,
  color: number,
) {
  const positions: number[] = [];
  for (const index of indices) {
    const anchor = anchors[index], value = vectors[index];
    if (!anchor || !value || !value.every(Number.isFinite)) continue;
    const vector = new THREE.Vector3(...value);
    if (vector.lengthSq() <= 1e-30) continue;
    if (normalize) vector.normalize();
    vector.multiplyScalar(lengthScale);
    positions.push(...anchor, anchor[0] + vector.x, anchor[1] + vector.y, anchor[2] + vector.z);
  }
  if (!positions.length) return;
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  root.add(new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.9 })));
}
function addNormalOverlays(
  root: any,
  surface: RenderSurfaceMesh,
  geometry: any,
  vectorFields: readonly VectorFieldDescriptor[],
  options: DisplayOptions,
) {
  const scale = surfaceScale(surface) * 0.08;
  if (options.showVertexNormals && surface.vertices?.length) {
    const canonical = vectorFields.find((field) =>
      field.meshId === surface.id
      && field.association === "VERTEX"
      && field.available
      && field.name.toLowerCase().includes("normal")
      && field.values.length === surface.vertices?.length
    );
    let vectors: readonly Vec3[] = canonical?.values ?? [];
    if (!canonical) {
      const attribute = geometry.getAttribute("normal");
      const computed: Vec3[] = [];
      if (attribute) for (let index = 0; index < attribute.count; index += 1) computed.push([attribute.getX(index), attribute.getY(index), attribute.getZ(index)]);
      vectors = computed;
    }
    const count = Math.min(surface.vertices.length, vectors.length);
    addLineVectors(
      root,
      surface.vertices.slice(0, count),
      vectors.slice(0, count),
      deterministicSampleIndices(count, 400),
      scale,
      true,
      canonical ? 0x34d399 : 0xf59e0b,
    );
  }
  if (options.showFaceNormals && surface.faces?.length) {
    const canonical = vectorFields.find((field) =>
      field.meshId === surface.id
      && field.association === "FACE"
      && field.available
      && field.name.toLowerCase().includes("normal")
      && field.values.length === surface.faces?.length
    );
    const anchors: Vec3[] = [], vectors: Vec3[] = [];
    const count = surface.faces.length;
    for (let index = 0; index < count; index += 1) {
      const anchor = faceCentroid(surface, index);
      const normal = canonical?.values[index] ?? faceNormal(surface, index);
      if (!anchor || !normal) continue;
      anchors.push(anchor); vectors.push(normal);
    }
    addLineVectors(root, anchors, vectors, deterministicSampleIndices(anchors.length, 300), scale, true, canonical ? 0x10b981 : 0xfbbf24);
  }
}
function addMeshVectorField(
  root: any,
  surface: RenderSurfaceMesh,
  field: VectorFieldDescriptor | undefined,
  options: DisplayOptions,
) {
  if (!field || !field.available || field.meshId !== surface.id || !surface.vertices || !surface.faces) return;
  const anchors: Vec3[] = [];
  if (field.association === "VERTEX") {
    anchors.push(...surface.vertices.slice(0, field.values.length));
  } else if (field.association === "FACE") {
    for (let index = 0; index < Math.min(surface.faces.length, field.values.length); index += 1) {
      const anchor = faceCentroid(surface, index);
      if (anchor) anchors.push(anchor);
    }
  } else {
    return;
  }
  const count = Math.min(anchors.length, field.values.length);
  const scale = options.vectorNormalize
    ? surfaceScale(surface) * 0.12 * options.vectorScale
    : options.vectorScale;
  addLineVectors(
    root,
    anchors.slice(0, count),
    field.values.slice(0, count),
    deterministicSampleIndices(count, Math.max(1, options.vectorGlyphCount)),
    scale,
    options.vectorNormalize,
    0xc084fc,
  );
}
function addSceneVectorField(
  root: any,
  data: RenderSceneData,
  field: VectorFieldDescriptor | undefined,
  options: DisplayOptions,
) {
  if (!field || !field.available || field.meshId) return;
  let anchors: Vec3[] = [];
  if (field.association === "BUBBLE") anchors = data.bubbles.map((bubble) => bubble.position).slice(0, field.values.length);
  else if (field.association === "ENVIRONMENT") anchors = [[0, 0, 0]];
  else return;
  const count = Math.min(anchors.length, field.values.length);
  const base = data.bubbles.length ? Math.max(...data.bubbles.map((bubble) => bubble.displayRadius)) : 0.001;
  const scale = options.vectorNormalize ? Math.max(1e-7, base) * 0.8 * options.vectorScale : options.vectorScale;
  addLineVectors(
    root,
    anchors.slice(0, count),
    field.values.slice(0, count),
    deterministicSampleIndices(count, Math.max(1, options.vectorGlyphCount)),
    scale,
    options.vectorNormalize,
    0xc084fc,
  );
}

export function createSceneController(canvas: HTMLCanvasElement, callbacks: SceneInteractionCallbacks = {}): SceneController {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  let qualityMode: RenderQualityMode = "AUTO";
  const coarsePointer = typeof matchMedia === "function" && matchMedia("(pointer: coarse)").matches;
  let renderPolicy = selectRenderingPolicy(qualityMode, Math.max(1, canvas.clientWidth), Math.max(1, canvas.clientHeight), devicePixelRatio, coarsePointer);
  renderer.setPixelRatio(renderPolicy.targetPixelRatio); renderer.outputColorSpace = THREE.SRGBColorSpace; renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.05;
  const scene = new THREE.Scene(); scene.background = new THREE.Color(0x07111f);
  const pmrem = new THREE.PMREMGenerator(renderer), room = new RoomEnvironment();
  const environmentTarget = pmrem.fromScene(room, 0.04); scene.environment = environmentTarget.texture; room.dispose(); pmrem.dispose();
  const camera = new THREE.PerspectiveCamera(50, 1, 0.000001, 1000), root = new THREE.Group(); scene.add(root);
  scene.add(new THREE.HemisphereLight(0xbfe9ff, 0x14213d, 1.15));
  const key = new THREE.DirectionalLight(0xffffff, 1.6); key.position.set(5, -4, 8); scene.add(key);
  const grid = new THREE.GridHelper(0.02, 20, 0x274060, 0x17263d); grid.rotation.x = Math.PI / 2; scene.add(grid);
  const raycaster = new THREE.Raycaster(), pointer = new THREE.Vector2(), placementPlane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0), pickObjects: any[] = [];
  raycaster.params.Line = { threshold: 0.00025 };
  raycaster.params.Points = { threshold: 0.00025 };
  let yaw = 0.8, pitch = 0.75, distance = 0.008; const target = new THREE.Vector3(0, 0, 0);
  let gesture = createGestureState(), desktopPan = false, appliedPixelRatio = renderPolicy.targetPixelRatio;
  const geometryCache = new Map<string, CachedSurfaceGeometry>();

  const updateCamera = () => {
    pitch = Math.max(0.08, Math.min(Math.PI - 0.08, pitch)); distance = Math.max(0.00002, Math.min(80, distance));
    const sinPitch = Math.sin(pitch);
    camera.position.set(target.x + distance * sinPitch * Math.cos(yaw), target.y + distance * sinPitch * Math.sin(yaw), target.z + distance * Math.cos(pitch));
    camera.lookAt(target);
  };
  const resize = () => {
    const rect = canvas.getBoundingClientRect(), width = Math.max(1, Math.floor(rect.width)), height = Math.max(1, Math.floor(rect.height));
    renderPolicy = selectRenderingPolicy(qualityMode, width, height, devicePixelRatio, coarsePointer);
    if (Math.abs(appliedPixelRatio - renderPolicy.targetPixelRatio) > 1e-6) {
      appliedPixelRatio = renderPolicy.targetPixelRatio;
      renderer.setPixelRatio(appliedPixelRatio);
    }
    const targetWidth = Math.floor(width * appliedPixelRatio), targetHeight = Math.floor(height * appliedPixelRatio);
    if (canvas.width !== targetWidth || canvas.height !== targetHeight) { renderer.setSize(width, height, false); camera.aspect = width / height; camera.updateProjectionMatrix(); }
  };
  const ndc = (clientX: number, clientY: number) => {
    const rect = canvas.getBoundingClientRect();
    pointer.set(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
    return pointer;
  };
  const disposeRoot = () => {
    while (root.children.length) {
      const child = root.children.pop(); if (!child) continue; root.remove(child);
      child.traverse?.((node: any) => {
        if (!node.userData?.cachedGeometry) node.geometry?.dispose?.();
        const material = node.material; if (Array.isArray(material)) material.forEach((item) => item.dispose?.()); else material?.dispose?.();
      });
    }
    pickObjects.length = 0;
  };
  const cachedSurfaceGeometry = (
    surface: RenderSurfaceMesh,
    data: RenderSceneData,
    decision: OpticalThicknessDecision,
  ): CachedSurfaceGeometry => {
    const cacheKey = [
      data.sourceKind,
      data.sourceId,
      surface.id,
      decision.source,
      decision.fieldAssociation ?? "NONE",
      decision.fieldValuesM?.length ?? 0,
    ].join(":");
    const cached = geometryCache.get(cacheKey);
    if (cached) return cached;
    const built = buildSurfaceGeometry(surface, decision);
    geometryCache.set(cacheKey, built);
    while (geometryCache.size > 32) {
      const oldest = geometryCache.keys().next().value as string | undefined;
      if (!oldest) break;
      const entry = geometryCache.get(oldest);
      entry?.geometry?.dispose?.(); entry?.thicknessTexture?.dispose?.();
      geometryCache.delete(oldest);
    }
    return built;
  };

  const addSurfaceMesh = (
    surface: RenderSurfaceMesh,
    data: RenderSceneData,
    selectedIds: Set<string>,
    selectedSurfaceId: string | null,
    options: DisplayOptions,
    scalarField: ScalarFieldDescriptor | undefined,
    scalarRange: ScalarRange | undefined,
    vectorFields: readonly VectorFieldDescriptor[],
    selectedVector: VectorFieldDescriptor | undefined,
  ) => {
    if (!options.showCanonicalMesh || !surface.renderable || !surface.vertices || !surface.faces || !filmVisible(surface.geometryRole, options.filmMode)) return;
    if (surface.geometryRole === "PLATEAU_BORDER" && !options.showJunctions) return;
    const status = featureFilmThicknessStatus(data.featureDisclosures);
    const decision = resolveOpticalThickness(status, candidateFromSurface(surface), options.interferenceMode, options.visualPreviewThicknessNm * 1e-9);
    const built = cachedSurfaceGeometry(surface, data, decision);
    const selected = selectedSurfaceId === surface.id || surface.ownerBubbleIds.some((id) => selectedIds.has(id));
    const shared = surface.geometryRole === "SHARED_FILM";

    if (options.showFaces) {
      const material = opticalMaterial(decision, selected, shared, built.thicknessTexture, renderPolicy.expensiveOptics);
      const mesh = new THREE.Mesh(built.geometry, material);
      mesh.userData.cachedGeometry = true;
      mesh.userData.opticalThicknessSource = decision.source;
      mesh.userData.pickTarget = { kind: "SURFACE", id: surface.id, ownerBubbleIds: [...surface.ownerBubbleIds] };
      pickObjects.push(mesh); root.add(mesh);
    } else {
      const pickMaterial = new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false, colorWrite: false, side: THREE.DoubleSide });
      const pickMesh = new THREE.Mesh(built.geometry, pickMaterial);
      pickMesh.userData.cachedGeometry = true;
      pickMesh.userData.pickTarget = { kind: "SURFACE", id: surface.id, ownerBubbleIds: [...surface.ownerBubbleIds] };
      pickObjects.push(pickMesh); root.add(pickMesh);
    }
    if (options.wireframe) addWireOverlay(root, built.geometry, shared);
    if (options.showVertices) addVertexPoints(root, surface);
    addNormalOverlays(root, surface, built.geometry, vectorFields, options);
    addScalarOverlay(root, surface, scalarField, scalarRange, data, built.geometry);
    addMeshVectorField(root, surface, selectedVector, options);
  };
  const addJunction = (junction: JunctionDescriptor, selectedSurfaceId: string | null) => {
    if (!junction.points || junction.points.length < 2) return;
    const geometry = new THREE.BufferGeometry().setFromPoints(junction.points.map((point) => new THREE.Vector3(...point)));
    const selected = selectedSurfaceId === `junction:${junction.id}`;
    const line = new THREE.Line(geometry, new THREE.LineBasicMaterial({
      color: selected ? 0xffffff : junction.provenanceSource === "TEST_FIXTURE" ? 0xf59e0b : 0x67e8f9,
      linewidth: selected ? 2 : 1,
    }));
    line.userData.pickTarget = { kind: "JUNCTION", id: junction.id };
    root.add(line); pickObjects.push(line);
  };
  const setData = (data: RenderSceneData, selectedIds: Set<string>, selectedSurfaceId: string | null, options: DisplayOptions) => {
    qualityMode = options.qualityMode;
    const rect = canvas.getBoundingClientRect();
    renderPolicy = selectRenderingPolicy(qualityMode, Math.max(1, rect.width), Math.max(1, rect.height), devicePixelRatio, coarsePointer);
    scene.environment = renderPolicy.expensiveOptics ? environmentTarget.texture : null;
    disposeRoot();

    const scalarFields = data.frame ? discoverScalarFields(data.frame, data.provenanceSource) : [];
    const vectorFields = data.frame ? discoverVectorFields(data.frame, data.provenanceSource) : [];
    const selectedScalar = scalarFields.find((field) => field.key === options.scalarChannel);
    const scalarRange = selectedScalar?.available
      ? resolveScalarRange(selectedScalar.values, {
        mode: options.scalarRangeMode,
        ...(typeof options.scalarMin === "number" ? { min: options.scalarMin } : {}),
        ...(typeof options.scalarMax === "number" ? { max: options.scalarMax } : {}),
        diverging: options.scalarDiverging,
      })
      : undefined;
    const selectedVector = vectorFields.find((field) => field.key === options.vectorChannel);

    data.surfaceMeshes.forEach((mesh) => addSurfaceMesh(
      mesh, data, selectedIds, selectedSurfaceId, options, selectedScalar, scalarRange, vectorFields, selectedVector,
    ));

    if (options.showSphereFallback && (options.filmMode === "ALL" || options.filmMode === "OUTER")) for (const bubble of data.bubbles) {
      if (!bubble.visible || bubble.shapeSource !== "VIEWER_SPHERE_FALLBACK") continue;
      let scalar = scalarValue(options.scalarChannel, bubble.physical);
      if (
        selectedScalar?.association === "BUBBLE"
        && selectedScalar.available
        && data.frame
        && selectedScalar.values.length === data.frame.bubbles.length
      ) {
        const bubbleIndex = data.frame.bubbles.findIndex((candidate) => candidate.id === bubble.id);
        if (bubbleIndex >= 0) scalar = selectedScalar.values[bubbleIndex];
      }
      const selected = selectedIds.has(bubble.id);
      const geometry = new THREE.SphereGeometry(bubble.displayRadius, renderPolicy.sphereWidthSegments, renderPolicy.sphereHeightSegments);
      const status = featureFilmThicknessStatus(data.featureDisclosures);
      const decision = resolveOpticalThickness(status, candidateFromBubble(bubble), options.interferenceMode, options.visualPreviewThicknessNm * 1e-9);
      let material: any;
      if (typeof scalar === "number" && Number.isFinite(scalar) && selectedScalar?.available === true && scalarRange) {
        material = new THREE.MeshPhysicalMaterial({
          color: new THREE.Color(...scalarRgb(scalar, scalarRange)), roughness: 0.04, metalness: 0, transmission: 0.82,
          transparent: true, opacity: selected ? 0.66 : 0.42, thickness: 0, ior: SOAP_FILM_IOR,
          side: THREE.DoubleSide, depthWrite: false,
        });
      } else {
        material = opticalMaterial(decision, selected, false, undefined, renderPolicy.expensiveOptics);
      }
      const mesh = new THREE.Mesh(geometry, material);
      mesh.position.set(...bubble.position);
      mesh.userData.pickTarget = { kind: "BUBBLE", id: bubble.id };
      mesh.userData.opticalThicknessSource = decision.source;
      root.add(mesh); pickObjects.push(mesh);
      if (options.wireframe) addWireOverlay(root, geometry, false);
    }

    if (options.showJunctions) data.junctions.forEach((junction) => addJunction(junction, selectedSurfaceId));
    addSceneVectorField(root, data, selectedVector, options);
  };
  const pickTarget = (clientX: number, clientY: number): PickTarget | null => {
    raycaster.setFromCamera(ndc(clientX, clientY), camera);
    const hit = raycaster.intersectObjects(pickObjects, false)[0];
    return hit?.object?.userData?.pickTarget ?? null;
  };
  const projectToPlacementPlane = (clientX: number, clientY: number): Vec3 | null => {
    raycaster.setFromCamera(ndc(clientX, clientY), camera);
    const point = new THREE.Vector3(), hit = raycaster.ray.intersectPlane(placementPlane, point);
    return hit ? [point.x, point.y, 0] : null;
  };
  const setCamera = (nextTarget: Vec3, nextDistance: number) => { target.set(...nextTarget); distance = nextDistance; updateCamera(); };
  const panCamera = (dx: number, dy: number) => {
    const scale = distance * 0.0018;
    const right = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 0), up = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 1);
    target.addScaledVector(right, -dx * scale); target.addScaledVector(up, dy * scale);
  };
  canvas.addEventListener("contextmenu", (event) => event.preventDefault());
  canvas.addEventListener("pointerdown", (event) => {
    canvas.setPointerCapture(event.pointerId);
    desktopPan = event.pointerType === "mouse" && (event.shiftKey || event.button === 1 || event.button === 2);
    const step = gesturePointerDown(gesture, event.pointerId, { x: event.clientX, y: event.clientY });
    gesture = step.state;
  });
  canvas.addEventListener("pointermove", (event) => {
    const step = gesturePointerMove(gesture, event.pointerId, { x: event.clientX, y: event.clientY });
    gesture = step.state;
    if (step.action.type === "ORBIT") {
      if (desktopPan || event.shiftKey) panCamera(step.action.dx, step.action.dy);
      else { yaw -= step.action.dx * 0.008; pitch -= step.action.dy * 0.008; }
      updateCamera(); callbacks.onCameraGesture?.();
    } else if (step.action.type === "PINCH_PAN") {
      distance *= step.action.zoomFactor;
      panCamera(step.action.panDx, step.action.panDy);
      updateCamera(); callbacks.onCameraGesture?.();
    }
  });
  canvas.addEventListener("pointerup", (event) => {
    const step = gesturePointerUp(gesture, event.pointerId, { x: event.clientX, y: event.clientY });
    gesture = step.state; desktopPan = false;
    if (step.tap) callbacks.onTap?.(step.tap.x, step.tap.y, event.shiftKey || event.metaKey || event.ctrlKey);
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointercancel", (event) => {
    gesture = gesturePointerCancel(gesture, event.pointerId); desktopPan = false;
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
  });
  canvas.addEventListener("wheel", (event) => { event.preventDefault(); distance *= Math.exp(event.deltaY * 0.001); updateCamera(); callbacks.onCameraGesture?.(); }, { passive: false });
  let frame = 0;
  const animate = () => { frame = requestAnimationFrame(animate); resize(); updateCamera(); renderer.render(scene, camera); };
  animate();
  return {
    camera, renderer, canvas, setData, setCamera, projectToPlacementPlane, pickTarget,
    dispose() {
      cancelAnimationFrame(frame); disposeRoot();
      for (const entry of geometryCache.values()) { entry.geometry.dispose?.(); entry.thicknessTexture?.dispose?.(); }
      geometryCache.clear(); environmentTarget.dispose(); renderer.dispose();
    },
  };
}
