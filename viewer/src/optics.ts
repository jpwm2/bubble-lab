import type { FeatureDisclosureStatus } from "./types.js";

export const AIR_IOR = 1.000277;
export const SOAP_FILM_IOR = 1.333;
export const VISIBLE_WAVELENGTHS_NM = [420, 460, 500, 540, 580, 620, 660] as const;

export type InterferenceMode = "AUTO" | "OFF" | "VISUAL_PREVIEW";
export type PhysicalThicknessKind = "SCALAR" | "VERTEX_FIELD" | "FACE_FIELD";
export interface PhysicalThicknessCandidate {
  kind: PhysicalThicknessKind;
  scalarM?: number;
  valuesM?: readonly number[];
  fieldName?: string;
}
export type OpticalThicknessSource =
  | "PHYSICAL_RESOLVED"
  | "PHYSICAL_MODELED"
  | "CONTRACT_INPUT"
  | "VISUAL_ONLY"
  | "NONE"
  | "BLOCKED_BY_DISCLOSURE";
export interface OpticalThicknessDecision {
  source: OpticalThicknessSource;
  thicknessM?: number;
  fieldValuesM?: readonly number[];
  fieldAssociation?: "VERTEX" | "FACE";
  fieldName?: string;
}

const clamp01 = (value: number) => Math.min(1, Math.max(0, Number.isFinite(value) ? value : 0));
const positiveIndex = (value: number) => Number.isFinite(value) && value > 0 ? value : 1;

export function normalIncidenceReflectance(n1: number, n2: number): number {
  const a = positiveIndex(n1), b = positiveIndex(n2);
  const ratio = (a - b) / (a + b);
  return clamp01(ratio * ratio);
}

export function fresnelSchlick(n1: number, n2: number, cosIncident: number): number {
  const r0 = normalIncidenceReflectance(n1, n2);
  const c = clamp01(cosIncident);
  return clamp01(r0 + (1 - r0) * Math.pow(1 - c, 5));
}

export function transmittedCosine(n1: number, n2: number, cosIncident: number): number {
  const a = positiveIndex(n1), b = positiveIndex(n2), c1 = clamp01(cosIncident);
  const sin1Sq = Math.max(0, 1 - c1 * c1);
  const sin2Sq = (a * a / (b * b)) * sin1Sq;
  if (sin2Sq >= 1) return 0;
  return Math.sqrt(Math.max(0, 1 - sin2Sq));
}

export function thinFilmPhase(
  thicknessM: number,
  wavelengthNm: number,
  filmIor = SOAP_FILM_IOR,
  cosFilm = 1,
): number {
  if (!Number.isFinite(thicknessM) || thicknessM < 0) return 0;
  const wavelengthM = Math.max(1e-12, wavelengthNm * 1e-9);
  return 4 * Math.PI * positiveIndex(filmIor) * thicknessM * clamp01(cosFilm) / wavelengthM;
}

function amplitudeS(n1: number, n2: number, c1: number, c2: number): number {
  const denominator = n1 * c1 + n2 * c2;
  return denominator === 0 ? 1 : (n1 * c1 - n2 * c2) / denominator;
}
function amplitudeP(n1: number, n2: number, c1: number, c2: number): number {
  const denominator = n2 * c1 + n1 * c2;
  return denominator === 0 ? 1 : (n2 * c1 - n1 * c2) / denominator;
}
function twoInterfaceReflectance(r12: number, r23: number, phase: number): number {
  const cosPhase = Math.cos(phase);
  const numerator = r12 * r12 + r23 * r23 + 2 * r12 * r23 * cosPhase;
  const coupling = r12 * r23;
  const denominator = 1 + coupling * coupling + 2 * coupling * cosPhase;
  return denominator <= 1e-15 ? 1 : clamp01(numerator / denominator);
}

export interface ThinFilmSample {
  thicknessM: number;
  wavelengthNm: number;
  cosIncident: number;
  nIncident?: number;
  nFilm?: number;
  nExit?: number;
}

export function thinFilmReflectance(sample: ThinFilmSample): number {
  const n1 = positiveIndex(sample.nIncident ?? AIR_IOR);
  const n2 = positiveIndex(sample.nFilm ?? SOAP_FILM_IOR);
  const n3 = positiveIndex(sample.nExit ?? AIR_IOR);
  const c1 = clamp01(sample.cosIncident);
  const c2 = transmittedCosine(n1, n2, c1);
  if (c2 === 0 && n1 > n2) return 1;
  const c3 = transmittedCosine(n2, n3, c2);
  if (c3 === 0 && n2 > n3) return 1;
  const phase = thinFilmPhase(sample.thicknessM, sample.wavelengthNm, n2, c2);
  const rs12 = amplitudeS(n1, n2, c1, c2), rs23 = amplitudeS(n2, n3, c2, c3);
  const rp12 = amplitudeP(n1, n2, c1, c2), rp23 = amplitudeP(n2, n3, c2, c3);
  return clamp01((twoInterfaceReflectance(rs12, rs23, phase) + twoInterfaceReflectance(rp12, rp23, phase)) * 0.5);
}

function gaussian(wavelengthNm: number, center: number, sigma: number): number {
  const x = (wavelengthNm - center) / sigma;
  return Math.exp(-0.5 * x * x);
}
function linearToSrgb(value: number): number {
  const x = clamp01(value);
  return x <= 0.0031308 ? 12.92 * x : 1.055 * Math.pow(x, 1 / 2.4) - 0.055;
}

export function thinFilmRgb(
  thicknessM: number,
  cosIncident: number,
  filmIor = SOAP_FILM_IOR,
): readonly [number, number, number] {
  let r = 0, g = 0, b = 0, rw = 0, gw = 0, bw = 0;
  for (const wavelengthNm of VISIBLE_WAVELENGTHS_NM) {
    const reflectance = thinFilmReflectance({ thicknessM, wavelengthNm, cosIncident, nFilm: filmIor });
    const rWeight = gaussian(wavelengthNm, 610, 45);
    const gWeight = gaussian(wavelengthNm, 545, 35);
    const bWeight = gaussian(wavelengthNm, 455, 30);
    r += reflectance * rWeight; rw += rWeight;
    g += reflectance * gWeight; gw += gWeight;
    b += reflectance * bWeight; bw += bWeight;
  }
  const exposure = 3.5;
  return [
    clamp01(linearToSrgb((r / Math.max(rw, 1e-12)) * exposure)),
    clamp01(linearToSrgb((g / Math.max(gw, 1e-12)) * exposure)),
    clamp01(linearToSrgb((b / Math.max(bw, 1e-12)) * exposure)),
  ];
}

export function featureFilmThicknessStatus(
  disclosures: Readonly<Record<string, FeatureDisclosureStatus>>,
): FeatureDisclosureStatus | undefined {
  for (const key of ["film_thickness", "thin_film_thickness", "filmThickness"]) {
    const value = disclosures[key];
    if (value) return value;
  }
  const entry = Object.entries(disclosures).find(([key]) => {
    const normalized = key.toLowerCase().replace(/[^a-z]/g, "");
    return normalized.includes("film") && normalized.includes("thickness");
  });
  return entry?.[1];
}

export function resolveOpticalThickness(
  featureStatus: FeatureDisclosureStatus | undefined,
  physical: PhysicalThicknessCandidate | undefined,
  mode: InterferenceMode,
  visualPreviewThicknessM: number,
): OpticalThicknessDecision {
  if (mode === "OFF") return { source: "NONE" };
  if (mode === "VISUAL_PREVIEW") {
    return {
      source: "VISUAL_ONLY",
      thicknessM: Math.max(0, Number.isFinite(visualPreviewThicknessM) ? visualPreviewThicknessM : 0),
    };
  }
  if (!physical) return { source: "NONE" };
  if (featureStatus === "NOT_IMPLEMENTED" || featureStatus === "VISUAL_ONLY") {
    return { source: "BLOCKED_BY_DISCLOSURE" };
  }
  const source: OpticalThicknessSource =
    featureStatus === "RESOLVED" ? "PHYSICAL_RESOLVED" :
    featureStatus === "MODELED" ? "PHYSICAL_MODELED" :
    "CONTRACT_INPUT";
  if (physical.kind === "SCALAR" && typeof physical.scalarM === "number") {
    const result: OpticalThicknessDecision = { source, thicknessM: physical.scalarM };
    if (physical.fieldName) result.fieldName = physical.fieldName;
    return result;
  }
  if (physical.valuesM) {
    const result: OpticalThicknessDecision = {
      source,
      fieldValuesM: physical.valuesM,
      fieldAssociation: physical.kind === "VERTEX_FIELD" ? "VERTEX" : "FACE",
    };
    if (physical.fieldName) result.fieldName = physical.fieldName;
    return result;
  }
  return { source: "NONE" };
}
