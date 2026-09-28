import type { Vec3 } from "./types.js";
export interface SphereBounds { center: Vec3; radius: number; }
export interface CameraFit { target: Vec3; distance: number; }
export function fitSpheres(spheres: readonly SphereBounds[], fovDegrees = 50): CameraFit {
  if (spheres.length === 0) return { target: [0, 0, 0], distance: 0.01 };
  let minX = Infinity, minY = Infinity, minZ = Infinity, maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity;
  for (const sphere of spheres) {
    minX = Math.min(minX, sphere.center[0] - sphere.radius); minY = Math.min(minY, sphere.center[1] - sphere.radius); minZ = Math.min(minZ, sphere.center[2] - sphere.radius);
    maxX = Math.max(maxX, sphere.center[0] + sphere.radius); maxY = Math.max(maxY, sphere.center[1] + sphere.radius); maxZ = Math.max(maxZ, sphere.center[2] + sphere.radius);
  }
  const target: Vec3 = [(minX + maxX) / 2, (minY + maxY) / 2, (minZ + maxZ) / 2];
  const dx = maxX - minX, dy = maxY - minY, dz = maxZ - minZ, radius = Math.max(Math.hypot(dx, dy, dz) / 2, 0.000001);
  const halfFov = (fovDegrees * Math.PI / 180) / 2;
  return { target, distance: Math.max(0.00002, (radius / Math.sin(halfFov)) * 1.16) };
}
