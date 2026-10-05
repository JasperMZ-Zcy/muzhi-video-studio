import React from 'react';

export type TransferRect = {x: number; y: number; width: number; height: number};
export type TransferItem = {
  id: string; label: string; source: TransferRect; target: TransferRect;
  checkAt: number; departAt: number; arriveAt: number; color?: string;
  /** Bound by the project wrapper to a real, hashed image/graphic/text layer. */
  visual?: React.ReactNode;
};
export type RowCanvasTransferProps = {
  frame: number; width?: number; height?: number; items: TransferItem[];
  theme?: {paper?: string; ink?: string; accent?: string; slot?: string};
};

const clamp = (v: number) => Math.max(0, Math.min(1, v));
const smooth = (v: number) => {const t = clamp(v); return t * t * (3 - 2 * t);};
const mix = (a: number, b: number, t: number) => a + (b - a) * t;
const validRect = (r: TransferRect, w: number, h: number) => r &&
  [r.x, r.y, r.width, r.height].every(Number.isFinite) && r.width >= 40 && r.height >= 28 &&
  r.x >= 0 && r.y >= 0 && r.x + r.width <= w && r.y + r.height <= h;

/** A list item has one visual instance through its flight. Its old slot becomes empty. */
export const validateRowCanvasTransfer = (p: RowCanvasTransferProps): string[] => {
  const errors: string[] = [];
  const w = p.width ?? 720, h = p.height ?? 1280;
  if (!Number.isFinite(p.frame) || p.frame < 0 || !Number.isFinite(w) || !Number.isFinite(h) ||
      w < 300 || h < 300) errors.push('frame and canvas must be finite and positive');
  if (!Array.isArray(p.items) || p.items.length < 1 || p.items.length > 12)
    return errors.concat('1-12 stable items required');
  const ids = new Set<string>();
  for (const item of p.items) {
    if (!item.id?.trim() || ids.has(item.id) || !item.label?.trim() || item.visual === null)
      errors.push('each transferred item needs one unique id and nonempty label');
    ids.add(item.id);
    if (!validRect(item.source, w, h) || !validRect(item.target, w, h))
      errors.push(`item ${item.id} needs two on-canvas rectangles`);
    if (![item.checkAt, item.departAt, item.arriveAt].every(Number.isInteger) ||
        item.checkAt < 0 || item.departAt < item.checkAt + 4 || item.arriveAt < item.departAt + 12)
      errors.push(`item ${item.id} needs check, departure and arrival in order`);
  }
  return errors;
};

export const transferPoseAt = (item: TransferItem, frame: number) => {
  const t = smooth((frame - item.departAt) / (item.arriveAt - item.departAt));
  const start = item.source, end = item.target;
  const lift = Math.min(130, Math.max(32, Math.abs(end.x - start.x) * .16));
  const x = mix(start.x, end.x, t);
  const y = mix(start.y, end.y, t) - lift * 4 * t * (1 - t);
  return {x, y, width: mix(start.width, end.width, t),
    height: mix(start.height, end.height, t), progress: t};
};

/** Project supplies item identity, labels, source and destination geometry, and cue frames. */
export const RowCanvasTransfer: React.FC<RowCanvasTransferProps> = (p) => {
  const errors = validateRowCanvasTransfer(p);
  if (errors.length) throw new Error(`RowCanvasTransfer: ${errors.join('; ')}`);
  const w = p.width ?? 720, h = p.height ?? 1280;
  const paper = p.theme?.paper ?? '#F8F4EA', ink = p.theme?.ink ?? '#183345';
  const accent = p.theme?.accent ?? '#CA683F', slot = p.theme?.slot ?? '#B7C3C0';
  return <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{background: paper}}
    data-transfer-count={p.items.length}>
    {p.items.map((item) => <rect key={`slot-${item.id}`} data-empty-slot={item.id}
      x={item.source.x} y={item.source.y} width={item.source.width} height={item.source.height}
      rx={8} fill="none" stroke={slot} strokeWidth={2}
      strokeDasharray={p.frame >= item.departAt ? '7 6' : undefined}/>)}
    {p.items.map((item) => {
      const pose = transferPoseAt(item, p.frame);
      const checked = p.frame >= item.checkAt;
      const isCard = pose.progress >= .5;
      return <g key={item.id} data-object-id={item.id}
        data-content-kind={item.visual === undefined ? 'label-fallback' : 'project-visual'}
        data-transfer-phase={p.frame < item.departAt ? 'source' :
          p.frame < item.arriveAt ? 'flight' : 'target'}>
        <rect x={pose.x} y={pose.y} width={pose.width} height={pose.height}
          rx={mix(8, 19, pose.progress)} fill="#FFFFFF" stroke={item.color ?? accent}
          strokeWidth={isCard ? 3 : 2}/>
        {checked && <circle cx={pose.x + 23} cy={pose.y + 23} r={9}
          fill={item.color ?? accent}/>}
        {item.visual === undefined ? <text x={pose.x + 43}
          y={pose.y + Math.min(pose.height - 9, pose.height * .58)}
          fill={ink} fontSize={mix(18, 24, pose.progress)} fontWeight={800}>{item.label}</text> :
          <foreignObject x={pose.x + 8} y={pose.y + 8}
            width={Math.max(1, pose.width - 16)} height={Math.max(1, pose.height - 16)}>
            <div style={{width: '100%', height: '100%', display: 'flex', alignItems: 'center',
              overflow: 'hidden'}}>{item.visual}</div>
          </foreignObject>}
      </g>;
    })}
  </svg>;
};
