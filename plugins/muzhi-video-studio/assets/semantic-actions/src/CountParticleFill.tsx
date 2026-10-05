import React from 'react';

export type CountParticleFillProps = {
  frame: number; width?: number; height?: number;
  layout?: 'classic' | 'unit-columns';
  columns: {id: string; label: string; value: number; color?: string}[];
  particleValue: number; unit: string; basis: string;
  dataStatus: 'measured' | 'illustrative';
  sourcePath?: string; sourceSha256?: string;
  events: {fallStart: number; fallEnd: number; readUntil: number};
  theme?: {paper?: string; ink?: string; accent?: string};
};
const clamp = (n: number) => Math.max(0, Math.min(1, n));
const smooth = (n: number) => {const t = clamp(n); return t * t * (3 - 2 * t);};

/** Every drawn grain represents exactly particleValue units; no free decorative particles. */
export const validateCountParticleFill = (p: CountParticleFillProps): string[] => {
  const errors: string[] = [];
  const w = p.width ?? 720, h = p.height ?? 1280;
  if (!Number.isFinite(p.frame) || p.frame < 0 || w < 300 || h < 300 ||
      !p.unit?.trim() || !p.basis?.trim() ||
      !['measured', 'illustrative'].includes(p.dataStatus))
    errors.push('frame, canvas, unit, basis and source status required');
  if (!Number.isSafeInteger(p.particleValue) || p.particleValue <= 0)
    errors.push('particleValue must be a positive integer');
  if (p.layout !== undefined && !['classic', 'unit-columns'].includes(p.layout))
    errors.push('layout must be classic or unit-columns');
  if (!Array.isArray(p.columns) || p.columns.length < 1 || p.columns.length > 5)
    return errors.concat('1-5 columns required');
  const ids = new Set<string>();
  let grains = 0;
  for (const column of p.columns) {
    if (!column.id?.trim() || ids.has(column.id) || !column.label?.trim() ||
        !Number.isSafeInteger(column.value) || column.value < 0 ||
        column.value % p.particleValue !== 0)
      errors.push('columns need stable IDs and values divisible by particleValue');
    ids.add(column.id);
    grains += column.value / p.particleValue;
  }
  if (grains > 200) errors.push('grain count exceeds readable/renderable 200; choose larger particleValue');
  if (p.layout === 'unit-columns' && (w < 680 || h < 600 ||
      p.columns.some((column) => !Number.isSafeInteger(column.value) ||
        column.value / p.particleValue > 12)))
    errors.push('unit-columns needs at least 680x600 and no more than 12 grains per column');
  if (p.dataStatus === 'measured' && (!p.sourcePath?.trim() ||
      p.sourcePath.startsWith('/') || p.sourcePath.includes('..') ||
      p.sourcePath.includes('\\') || !/^[0-9a-f]{64}$/i.test(p.sourceSha256 || '')))
    errors.push('measured count needs bound project-relative source and SHA-256');
  const e = p.events;
  if (!e || ![e.fallStart, e.fallEnd, e.readUntil].every(Number.isInteger) ||
      e.fallStart < 0 || e.fallEnd <= e.fallStart || e.readUntil < e.fallEnd + 15)
    errors.push('fall then settled read window required');
  return errors;
};

export const CountParticleFill: React.FC<CountParticleFillProps> = (p) => {
  const errors = validateCountParticleFill(p);
  if (errors.length) throw new Error(`CountParticleFill: ${errors.join('; ')}`);
  const w = p.width ?? 720, h = p.height ?? 1280;
  const paper = p.theme?.paper ?? '#F8F4EA', ink = p.theme?.ink ?? '#183345';
  const accent = p.theme?.accent ?? '#CA683F';
  const unitColumns = p.layout === 'unit-columns';
  const cell = (w - 100) / p.columns.length;
  const baseline = h * (unitColumns ? .68 : .76);
  const maxGrains = Math.max(1, ...p.columns.map((column) => column.value / p.particleValue));
  const perRow = unitColumns ? 1 : 8;
  const maxRows = Math.ceil(maxGrains / perRow);
  const dotGap = unitColumns ? Math.min(44, (h * .4) / Math.max(1, maxRows - 1), cell * .38) :
    Math.min(20, (h * .43) / maxRows, cell / 9);
  const dotRadius = unitColumns ? Math.min(14, Math.max(9, dotGap * .32)) : Math.max(3, dotGap * .3);
  const headingY = unitColumns ? h * .12 : h * .2;
  return <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{background: paper}}
    data-grain-unit={p.particleValue} data-data-status={p.dataStatus}
    data-layout={unitColumns ? 'unit-columns' : undefined}>
    <text x={50} y={headingY} fontSize={unitColumns ? 27 : 25} fontWeight={800} fill={ink}>{p.basis}</text>
    <text x={50} y={headingY + 34} fontSize={unitColumns ? 20 : 18} fill={ink}>
      {p.dataStatus === 'illustrative' ? '教学示意' : '已绑来源'} · 每粒 = {p.particleValue}{p.unit}
    </text>
    {p.columns.map((column, ci) => {
      const count = column.value / p.particleValue;
      const centerX = 50 + (ci + .5) * cell;
      return <g key={column.id} data-column-id={column.id} data-count={count}>
        {Array.from({length: count}, (_, i) => {
          const release = p.events.fallStart + (p.events.fallEnd - p.events.fallStart) * i / Math.max(1, count);
          const duration = Math.max(6, (p.events.fallEnd - p.events.fallStart) / Math.max(3, count));
          const t = smooth((p.frame - release) / duration);
          const targetX = centerX + ((i % perRow) - (perRow - 1) / 2) * dotGap;
          const targetY = baseline - Math.floor(i / perRow) * dotGap;
          const y = -20 + (targetY + 20) * t;
          return t > 0 && <circle key={i} data-grain-index={i} cx={targetX} cy={y}
            r={dotRadius} fill={column.color ?? accent}/>;
        })}
        <text x={centerX} y={baseline + (unitColumns ? 45 : 40)} textAnchor="middle"
          fontSize={unitColumns ? 25 : 20} fill={ink}>{column.label}</text>
        <text x={centerX} y={baseline + (unitColumns ? 80 : 70)} textAnchor="middle"
          fontSize={unitColumns ? 29 : 22} fontWeight={800}
          fill={ink}>{column.value}{p.unit}</text>
      </g>;
    })}
  </svg>;
};
