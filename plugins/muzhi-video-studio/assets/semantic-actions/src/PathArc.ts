export type PathPoint = {x: number; y: number};
export type CubicPath = [PathPoint, PathPoint, PathPoint, PathPoint];
const mix = (a: number, b: number, t: number) => a + (b - a) * t;
const valid = (p: PathPoint) => p && Number.isFinite(p.x) && Number.isFinite(p.y);

export const validateCubicPath = (path: CubicPath): string[] =>
  !Array.isArray(path) || path.length !== 4 || !path.every(valid) ?
    ['cubic path needs four finite control points'] : [];

export const cubicPointAt = (path: CubicPath, t: number): PathPoint => {
  const errors = validateCubicPath(path);
  if (errors.length || !Number.isFinite(t) || t < 0 || t > 1)
    throw new Error(`cubicPointAt: ${errors.join('; ') || 't outside 0..1'}`);
  const a = {x: mix(path[0].x, path[1].x, t), y: mix(path[0].y, path[1].y, t)};
  const b = {x: mix(path[1].x, path[2].x, t), y: mix(path[1].y, path[2].y, t)};
  const c = {x: mix(path[2].x, path[3].x, t), y: mix(path[2].y, path[3].y, t)};
  const d = {x: mix(a.x, b.x, t), y: mix(a.y, b.y, t)};
  const e = {x: mix(b.x, c.x, t), y: mix(b.y, c.y, t)};
  return {x: mix(d.x, e.x, t), y: mix(d.y, e.y, t)};
};

/** Integrates a cubic path; time fraction and traveled fraction remain separate. */
export const cubicArcAt = (path: CubicPath, t: number, subdivisions = 200) => {
  if (!Number.isInteger(subdivisions) || subdivisions < 32 || subdivisions > 4096)
    throw new Error('subdivisions must be an integer in 32..4096');
  const endpoint = cubicPointAt(path, t);
  let total = 0, traveled = 0, previous = cubicPointAt(path, 0);
  for (let i = 1; i <= subdivisions; i++) {
    const point = cubicPointAt(path, i / subdivisions);
    const length = Math.hypot(point.x - previous.x, point.y - previous.y);
    total += length;
    if (i / subdivisions <= t) traveled += length;
    previous = point;
  }
  if (total <= 0) throw new Error('cubic path has zero length');
  return {endpoint, timeFraction: t, arcFraction: t === 1 ? 1 : traveled / total,
    totalLengthApprox: total, subdivisions};
};
