export type StackPart = {id: string; value: number};
export type ChartPoint = {x: number; y: number};
const clamp = (n: number) => Math.max(0, Math.min(1, n));
const mix = (a: number, b: number, t: number) => a + (b - a) * t;

export const validateStack = (parts: StackPart[], total: number): string[] => {
  const errors: string[] = [];
  if (!Number.isFinite(total) || total <= 0 || !Array.isArray(parts) ||
      parts.length < 1 || parts.length > 20) return ['positive denominator and 1-20 parts required'];
  const ids = new Set<string>();
  for (const part of parts) {
    if (!part.id?.trim() || ids.has(part.id) || !Number.isFinite(part.value) || part.value < 0)
      errors.push('stack parts need unique IDs and nonnegative finite values');
    ids.add(part.id);
  }
  if (Math.abs(parts.reduce((sum, item) => sum + item.value, 0) - total) >
      Math.max(1e-8, total * 1e-10)) errors.push('stack sum differs from denominator');
  return errors;
};

/** All visual segments derive from the same values and one explicit denominator. */
export const stackAt = (parts: StackPart[], total: number, height: number, progress: number) => {
  const errors = validateStack(parts, total);
  if (errors.length || !Number.isFinite(height) || height <= 0 || !Number.isFinite(progress))
    throw new Error(`stackAt: ${errors.join('; ') || 'height/progress invalid'}`);
  let cursor = 0;
  return parts.map((part) => {
    const start = cursor;
    const length = height * part.value / total * clamp(progress);
    cursor += length;
    return {id: part.id, start, length, value: part.value, fraction: part.value / total};
  });
};

export const validatePolyline = (points: ChartPoint[]): string[] => {
  if (!Array.isArray(points) || points.length < 2 || points.length > 128 ||
      points.some((p) => !p || ![p.x, p.y].every(Number.isFinite)))
    return ['2-128 finite chart points required'];
  if (points.some((p, i) => i > 0 && p.x <= points[i - 1].x))
    return ['chart x values must increase strictly'];
  return [];
};

/** Drawn path, cursor and displayed readout share one sampled endpoint. */
export const polylineAt = (points: ChartPoint[], progress: number) => {
  const errors = validatePolyline(points);
  if (errors.length || !Number.isFinite(progress))
    throw new Error(`polylineAt: ${errors.join('; ') || 'progress invalid'}`);
  const u = clamp(progress) * (points.length - 1);
  const index = Math.min(points.length - 2, Math.floor(u));
  const fraction = u - index;
  const endpoint = {x: mix(points[index].x, points[index + 1].x, fraction),
    y: mix(points[index].y, points[index + 1].y, fraction)};
  return {endpoint, drawn: [...points.slice(0, index + 1), endpoint], readout: endpoint.y};
};
