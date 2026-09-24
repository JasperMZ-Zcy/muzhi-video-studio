import React from "react";
import {
  Easing,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { PAPER_INK_THEME, PaperInkTheme, paperBackground } from "./theme";

export type TimelineStep = {
  index: string;
  title: string;
  detail: string;
};

export type TimelineProgressProps = {
  eyebrow: string;
  title: string;
  steps: TimelineStep[];
  demoLabel: string;
  theme?: PaperInkTheme;
};

/**
 * Ref-inspired adaptation of video-shotcraft's TimelineTravel. The camera-like
 * move becomes a vertical reading cursor so the sequence remains legible in 9:16.
 */
export const TimelineProgress: React.FC<TimelineProgressProps> = ({
  eyebrow,
  title,
  steps,
  demoLabel,
  theme = PAPER_INK_THEME,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const safeSteps = steps.slice(0, 3);
  const trackTop = 336;
  const gap = 242;
  const cursorY = interpolate(frame, [22, 145], [trackTop, trackTop + gap * 2], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });
  const lineGrow = interpolate(frame, [10, 140], [0, gap * 2], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });

  return (
    <div
      style={{
        position: "relative",
        width: "100%",
        height: "100%",
        overflow: "hidden",
        background: paperBackground(theme),
        color: theme.ink,
        fontFamily: theme.fontFamily,
        opacity: 1,
      }}
    >
      <div
        style={{
          position: "absolute",
          top: 86,
          left: 64,
          right: 64,
          opacity: 1,
        }}
      >
        <div style={{ color: theme.inkSoft, fontSize: 19, fontWeight: 700, letterSpacing: 2 }}>
          {eyebrow}
        </div>
        <div style={{ marginTop: 18, fontSize: 55, fontWeight: 800, lineHeight: 1.18, letterSpacing: -2 }}>
          {title}
        </div>
      </div>

      <div style={{ position: "absolute", left: 136, top: trackTop, height: gap * 2, width: 3, background: theme.rule }} />
      <div style={{ position: "absolute", left: 136, top: trackTop, height: lineGrow, width: 4, background: theme.amber }} />
      <div
        style={{
          position: "absolute",
          left: 116,
          top: cursorY - 20,
          width: 44,
          height: 44,
          borderRadius: 22,
          background: theme.amber,
          border: `7px solid ${theme.paper}`,
          boxShadow: `0 0 0 2px ${theme.amber}`,
        }}
      />

      {safeSteps.map((step, index) => {
        const popAt = index * 45;
        const settle = spring({
          frame: frame - popAt,
          fps,
          config: { damping: 18, stiffness: 190, mass: 0.7 },
        });
        const visible = index === 0 ? 1 : interpolate(frame, [popAt, popAt + 10], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        const isCurrent = frame >= popAt && frame < popAt + 46;
        const rowY = trackTop - 72 + index * gap;
        return (
          <div
            key={step.index}
            style={{
              position: "absolute",
              left: 194,
              top: rowY,
              right: 54,
              display: "grid",
              gridTemplateColumns: "74px 1fr",
              columnGap: 20,
              alignItems: "start",
              opacity: visible,
              translate: `${index === 0 ? 0 : interpolate(settle, [0, 1], [52, 0])}px 0px`,
            }}
          >
            <div
              style={{
                width: 68,
                height: 68,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: isCurrent ? theme.paper : theme.inkSoft,
                background: isCurrent ? theme.ink : "transparent",
                border: `1px solid ${isCurrent ? theme.ink : theme.rule}`,
                fontSize: 19,
                fontWeight: 800,
                letterSpacing: 1,
              }}
            >
              {step.index}
            </div>
            <div style={{ paddingTop: 2 }}>
              <div style={{ fontSize: 37, lineHeight: 1.2, fontWeight: 800 }}>{step.title}</div>
              <div style={{ marginTop: 11, maxWidth: 390, color: theme.inkSoft, fontSize: 24, lineHeight: 1.45, fontWeight: 600 }}>
                {step.detail}
              </div>
            </div>
          </div>
        );
      })}

      <div
        style={{
          position: "absolute",
          left: 64,
          right: 64,
          bottom: 84,
          paddingTop: 20,
          borderTop: `1px solid ${theme.rule}`,
          color: theme.inkSoft,
          fontSize: 22,
          fontWeight: 700,
        }}
      >
        顺序推进，不把结论抢在证据前面
      </div>
      <div style={{ position: "absolute", left: 64, bottom: 34, color: theme.inkSoft, fontSize: 17, letterSpacing: 1.5, fontWeight: 700 }}>
        {demoLabel}
      </div>
    </div>
  );
};
