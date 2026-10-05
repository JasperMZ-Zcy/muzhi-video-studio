import React from 'react';

export type PolarContourMorphProps = {
  frame: number; width?: number; height?: number;
  center: {x: number; y: number};
  fromRadii: number[]; toRadii: number[];
  events: {morphStart: number; morphEnd: number; readUntil: number};
  label?: string; theme?: {paper?: string; fill?: string; stroke?: string; ink?: string};
};
const clamp = (n: number) => Math.max(0, Math.min(1, n));
const smooth = (n: number) => {const t = clamp(n); return t * t * (3 - 2 * t);};
const mix = (a: number, b: number, t: number) => a + (b - a) * t;

/** Only matching radial samples of two simple star-shaped closed contours are supported. */
export const validatePolarContourMorph = (p: PolarContourMorphProps): string[] => {
  const errors: string[] = [];
  const w = p.width ?? 720, h = p.height ?? 1280;
  const radius = Math.max(...(p.fromRadii || []), ...(p.toRadii || []));
  if (!Number.isFinite(p.frame) || p.frame < 0 || !Number.isFinite(w) || !Number.isFinite(h) ||
      w < 200 || h < 200 || !p.center || ![p.center.x, p.center.y].every(Number.isFinite))
    errors.push('frame, canvas and center invalid');
  if (!Array.isArray(p.fromRadii) || !Array.isArray(p.toRadii) || p.fromRadii.length < 16 ||
      p.fromRadii.length > 256 || p.fromRadii.length !== p.toRadii.length ||
      [...p.fromRadii, ...p.toRadii].some((r) => !Number.isFinite(r) || r <= 0))
    errors.push('equal 16-256 positive radial samples required');
  if (Number.isFinite(radius) && p.center && (p.center.x - radius < 0 || p.center.y - radius < 0 ||
      p.center.x + radius > w || p.center.y + radius > h))
    errors.push('entire contour must fit canvas');
  const e = p.events;
  if (!e || ![e.morphStart, e.morphEnd, e.readUntil].every(Number.isInteger) ||
      e.morphStart < 0 || e.morphEnd <= e.morphStart || e.readUntil < e.morphEnd + 12)
    errors.push('morph then settled reading required');
  return errors;
};

export const polarContourPathAt = (p: PolarContourMorphProps, frame = p.frame): string => {
  const t = smooth((frame - p.events.morphStart) / (p.events.morphEnd - p.events.morphStart));
  return p.fromRadii.map((r, i) => {
    const angle = i * Math.PI * 2 / p.fromRadii.length;
    const radius = mix(r, p.toRadii[i], t);
    const x = p.center.x + radius * Math.cos(angle);
    const y = p.center.y + radius * Math.sin(angle);
    return `${i ? 'L' : 'M'}${x.toFixed(2)} ${y.toFixed(2)}`;
  }).join(' ') + ' Z';
};

export const PolarContourMorph: React.FC<PolarContourMorphProps> = (p) => {
  const errors = validatePolarContourMorph(p);
  if (errors.length) throw new Error(`PolarContourMorph: ${errors.join('; ')}`);
  const w = p.width ?? 720, h = p.height ?? 1280;
  const paper = p.theme?.paper ?? '#F8F4EA', fill = p.theme?.fill ?? '#CDD9D4';
  const stroke = p.theme?.stroke ?? '#183345', ink = p.theme?.ink ?? stroke;
  return <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{background: paper}}
    data-contour-kind="single-star-shaped-closed" data-contour-samples={p.fromRadii.length}>
    <path d={polarContourPathAt(p)} fill={fill} stroke={stroke} strokeWidth={3}/>
    {p.label && <text x={w / 2} y={h - 70} textAnchor="middle" fontSize={23} fill={ink}>{p.label}</text>}
  </svg>;
};
