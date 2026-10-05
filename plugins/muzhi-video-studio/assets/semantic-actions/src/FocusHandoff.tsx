import React from 'react';

export type FocusHandoffProps = {
  frame: number; width?: number; height?: number;
  from: {id: string; visual: React.ReactNode};
  to: {id: string; visual: React.ReactNode};
  events: {fromHoldUntil: number; toStart: number; fromGoneAt: number; toSettledAt: number};
  theme?: {background?: string};
};
const clamp = (n: number) => Math.max(0, Math.min(1, n));
const smooth = (n: number) => {const t = clamp(n); return t * t * (3 - 2 * t);};

export const validateFocusHandoff = (p: FocusHandoffProps): string[] => {
  const errors: string[] = [];
  const e = p.events;
  if (!Number.isFinite(p.frame) || p.frame < 0 ||
      (p.width !== undefined && (!Number.isFinite(p.width) || p.width < 200)) ||
      (p.height !== undefined && (!Number.isFinite(p.height) || p.height < 200)))
    errors.push('frame and canvas invalid');
  if (!p.from?.id?.trim() || !p.to?.id?.trim() || p.from.id === p.to.id ||
      p.from.visual == null || p.to.visual == null)
    errors.push('two distinct scene identities and actual visual nodes required');
  if (!e || ![e.fromHoldUntil, e.toStart, e.fromGoneAt, e.toSettledAt].every(Number.isInteger) ||
      e.fromHoldUntil < 0 || e.toStart < e.fromHoldUntil ||
      e.toStart >= e.fromGoneAt || e.fromGoneAt > e.toSettledAt ||
      e.toSettledAt - e.toStart < 8)
    errors.push('ordered hold, staggered focus crossing and settling required');
  return errors;
};

/** Both supplied visuals stay project-owned; this only transfers focus. */
export const FocusHandoff: React.FC<FocusHandoffProps> = (p) => {
  const errors = validateFocusHandoff(p);
  if (errors.length) throw new Error(`FocusHandoff: ${errors.join('; ')}`);
  const e = p.events, width = p.width ?? 720, height = p.height ?? 1280;
  const outgoing = smooth((p.frame - e.fromHoldUntil) / (e.fromGoneAt - e.fromHoldUntil));
  const incoming = smooth((p.frame - e.toStart) / (e.toSettledAt - e.toStart));
  const layer = (id: string, node: React.ReactNode, opacity: number, blur: number, shift: number) =>
    <div data-focus-id={id} style={{position: 'absolute', inset: 0,
      opacity, filter: `blur(${blur}px)`, transform: `translateX(${shift}px)`}}>{node}</div>;
  return <div style={{position: 'relative', width, height, overflow: 'hidden',
    background: p.theme?.background ?? '#F8F4EA'}} data-focus-phase={
      p.frame < e.fromHoldUntil ? 'from' : p.frame >= e.toSettledAt ? 'to' : 'handoff'}>
    {layer(p.from.id, p.from.visual, 1 - outgoing, outgoing * 8, -outgoing * 32)}
    {layer(p.to.id, p.to.visual, incoming, (1 - incoming) * 8, (1 - incoming) * 30)}
  </div>;
};
