export type SceneRect = {x: number; y: number; width: number; height: number};
export type ScenePoint = {x: number; y: number};
export type CameraMove = {
  viewport: {width: number; height: number};
  target: SceneRect;
  fromScale: number; toScale: number;
  startFrame: number; endFrame: number;
  minVisibleFraction?: number;
};
const clamp = (n: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, n));
const smooth = (n: number) => {const t = clamp(n, 0, 1); return t * t * (3 - 2 * t);};
const mix = (a: number, b: number, t: number) => a + (b - a) * t;

export const validateCameraMove = (m: CameraMove): string[] => {
  const errors: string[] = [];
  const {viewport: v, target: r} = m;
  if (!v || !r || ![v.width, v.height, r.x, r.y, r.width, r.height,
    m.fromScale, m.toScale].every(Number.isFinite) ||
    v.width <= 0 || v.height <= 0 || r.width <= 0 || r.height <= 0 ||
    r.x < 0 || r.y < 0 || r.x + r.width > v.width || r.y + r.height > v.height ||
    m.fromScale <= 0 || m.toScale <= 0)
    errors.push('target and camera need finite on-canvas geometry');
  const fraction = m.minVisibleFraction ?? .88;
  if (!Number.isFinite(fraction) || fraction <= 0 || fraction > 1 ||
    (r && v && (r.width * m.toScale > v.width * fraction ||
      r.height * m.toScale > v.height * fraction)))
    errors.push('zoom target would clip its required reading area');
  if (![m.startFrame, m.endFrame].every(Number.isInteger) ||
    m.startFrame < 0 || m.endFrame <= m.startFrame)
    errors.push('ordered camera frames required');
  return errors;
};

/** One affine transform drives sources, links, highlights and pointer position. */
export const cameraAt = (m: CameraMove, frame: number) => {
  if (!Number.isFinite(frame) || frame < 0) throw new Error('cameraAt needs a non-negative local frame');
  const errors = validateCameraMove(m);
  if (errors.length) throw new Error(`cameraAt: ${errors.join('; ')}`);
  const t = smooth((frame - m.startFrame) / (m.endFrame - m.startFrame));
  const s = mix(m.fromScale, m.toScale, t);
  const cx = m.viewport.width / 2, cy = m.viewport.height / 2;
  const targetX = m.target.x + m.target.width / 2;
  const targetY = m.target.y + m.target.height / 2;
  // At t=0 the caller's scene is not shifted; at t=1 the target is centered.
  const tx = -(targetX - cx) * s * t;
  const ty = -(targetY - cy) * s * t;
  const project = (point: ScenePoint): ScenePoint => ({
    x: cx + (point.x - cx) * s + tx,
    y: cy + (point.y - cy) * s + ty,
  });
  return {scale: s, translate: {x: tx, y: ty}, project,
    projectRect: (rect: SceneRect) => {
      const corner = project({x: rect.x, y: rect.y});
      return {...corner, width: rect.width * s, height: rect.height * s};
    },
    pointer: (sourcePoint: ScenePoint, desiredPixelSize: number) => {
      if (!Number.isFinite(desiredPixelSize) || desiredPixelSize <= 0)
        throw new Error('pointer needs a positive screen pixel size');
      return {position: project(sourcePoint), innerSize: desiredPixelSize / s,
        screenSize: desiredPixelSize};
    },
  };
};

export type ScrollBrake = {
  contentHeight: number; viewportHeight: number; target: {y: number; height: number};
  startFrame: number; brakeFrame: number; settledFrame: number;
  overshootPixels?: number;
};

export const validateScrollBrake = (s: ScrollBrake): string[] => {
  const errors: string[] = [];
  if (![s.contentHeight, s.viewportHeight, s.target?.y, s.target?.height].every(Number.isFinite) ||
    s.contentHeight <= 0 || s.viewportHeight <= 0 || s.viewportHeight > s.contentHeight ||
    s.target.y < 0 || s.target.height <= 0 || s.target.y + s.target.height > s.contentHeight ||
    s.target.height > s.viewportHeight)
    errors.push('target must fit actual scroll domain and reading viewport');
  if (![s.startFrame, s.brakeFrame, s.settledFrame].every(Number.isInteger) ||
    s.startFrame < 0 || s.brakeFrame <= s.startFrame || s.settledFrame <= s.brakeFrame)
    errors.push('ordered scroll and brake frames required');
  if (s.overshootPixels !== undefined && (!Number.isFinite(s.overshootPixels) ||
      s.overshootPixels < 0 || s.overshootPixels > 60))
    errors.push('overshoot must be bounded at 0-60 source pixels');
  return errors;
};

/** Measured source-pixel scroll; optional overshoot is clamped at the actual page edge. */
export const scrollBrakeAt = (s: ScrollBrake, frame: number) => {
  if (!Number.isFinite(frame) || frame < 0) throw new Error('scrollBrakeAt needs a non-negative local frame');
  const errors = validateScrollBrake(s);
  if (errors.length) throw new Error(`scrollBrakeAt: ${errors.join('; ')}`);
  const maxScroll = s.contentHeight - s.viewportHeight;
  const stop = clamp(s.target.y + s.target.height / 2 - s.viewportHeight / 2, 0, maxScroll);
  const peak = clamp(stop + (s.overshootPixels ?? 0), 0, maxScroll);
  const offset = frame < s.brakeFrame ? mix(0, peak,
    smooth((frame - s.startFrame) / (s.brakeFrame - s.startFrame))) :
    mix(peak, stop, smooth((frame - s.brakeFrame) / (s.settledFrame - s.brakeFrame)));
  return {offset, stop, maxScroll, settled: frame >= s.settledFrame};
};
