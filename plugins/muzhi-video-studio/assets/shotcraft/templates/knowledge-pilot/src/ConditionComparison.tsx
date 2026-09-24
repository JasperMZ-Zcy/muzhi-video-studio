import React from "react";
import {
  Easing,
  interpolate,
  useCurrentFrame,
} from "remotion";
import { PAPER_INK_THEME, PaperInkTheme, paperBackground } from "./theme";

export type ComparisonColumn = {
  label: string;
  prompts: string[];
};

export type ConditionComparisonProps = {
  eyebrow: string;
  title: string;
  left: ComparisonColumn;
  right: ComparisonColumn;
  evidenceLine: string;
  demoLabel: string;
  theme?: PaperInkTheme;
};

const DOTS = Array.from({ length: 24 }, (_, index) => ({
  x: 75 + (index % 6) * 42,
  y: 29 + Math.floor(index / 6) * 42,
}));

/**
 * Ref-inspired adaptation of video-shotcraft's UnitDotSwarmRegroupV2. Dots
 * represent unlabeled comparison notes, not measurements; they split to make
 * a condition check visually concrete without inventing real-world data.
 */
export const ConditionComparison: React.FC<ConditionComparisonProps> = ({
  eyebrow,
  title,
  left,
  right,
  evidenceLine,
  demoLabel,
  theme = PAPER_INK_THEME,
}) => {
  const frame = useCurrentFrame();
  const gather = interpolate(frame, [20, 82], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });
  const verified = interpolate(frame, [90, 135], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
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
      <div style={{ position: "absolute", top: 86, left: 64, right: 64 }}>
        <div style={{ color: theme.inkSoft, fontSize: 19, fontWeight: 700, letterSpacing: 2 }}>{eyebrow}</div>
        <div style={{ marginTop: 18, maxWidth: 590, fontSize: 52, fontWeight: 800, lineHeight: 1.18, letterSpacing: -2 }}>{title}</div>
      </div>

      <div style={{ position: "absolute", top: 334, left: 64, right: 64, display: "grid", gridTemplateColumns: "1fr 52px 1fr", alignItems: "stretch", columnGap: 16 }}>
        {[left, right].map((column, columnIndex) => {
          const entry = interpolate(frame, [0, 16 + columnIndex * 8], [0.82, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: Easing.out(Easing.cubic),
          });
          const side = columnIndex === 0 ? -1 : 1;
          return (
            <div
              key={column.label}
              style={{
                gridColumn: columnIndex === 0 ? 1 : 3,
                minHeight: 472,
                padding: "28px 22px",
                background: theme.panelSurface,
                borderTop: `5px solid ${columnIndex === 0 ? theme.ink : theme.amber}`,
                borderBottom: `1px solid ${theme.rule}`,
                opacity: entry,
                translate: `${interpolate(entry, [0, 1], [side * 36, 0])}px 0px`,
              }}
            >
              <div style={{ color: columnIndex === 0 ? theme.ink : theme.amber, fontSize: 28, fontWeight: 800 }}>{column.label}</div>
              <div style={{ marginTop: 26, display: "flex", flexDirection: "column", gap: 20 }}>
                {column.prompts.slice(0, 3).map((prompt, index) => {
                  const promptIn = interpolate(frame, [40 + index * 13, 53 + index * 13], [0, 1], {
                    extrapolateLeft: "clamp",
                    extrapolateRight: "clamp",
                  });
                  return (
                    <div key={prompt} style={{ opacity: promptIn, fontSize: 24, lineHeight: 1.36, fontWeight: 700, color: theme.inkSoft }}>
                      <span style={{ color: theme.amber, paddingRight: 8 }}>—</span>{prompt}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
        <div style={{ gridColumn: 2, display: "flex", alignItems: "center", justifyContent: "center", color: theme.inkSoft, fontSize: 20, fontWeight: 800 }}>
          对照
        </div>
      </div>

      <svg width="720" height="260" viewBox="0 0 720 260" style={{ position: "absolute", left: 0, top: 816 }}>
        <line x1="78" y1="196" x2="642" y2="196" stroke={theme.rule} strokeWidth="2" />
        {DOTS.map((dot, index) => {
          const targetX = index % 2 === 0 ? 205 + (index % 6) * 14 : 420 + (index % 6) * 14;
          const targetY = 68 + Math.floor(index / 6) * 34;
          const x = dot.x + (targetX - dot.x) * gather;
          const y = dot.y + (targetY - dot.y) * gather;
          const fill = index % 2 === 0 ? theme.ink : theme.amber;
          return <circle key={index} cx={x} cy={y} r="7" fill={fill} opacity="0.9" />;
        })}
        <line x1="188" y1="206" x2={188 + 126 * verified} y2="206" stroke={theme.ink} strokeWidth="4" />
        <line x1="406" y1="206" x2={406 + 126 * verified} y2="206" stroke={theme.amber} strokeWidth="4" />
      </svg>
      <div style={{ position: "absolute", top: 814, left: 64, color: theme.inkSoft, fontSize: 18, fontWeight: 700, letterSpacing: 1 }}>
        对照笔记 · 非数据
      </div>

      <div
        style={{
          position: "absolute",
          left: 64,
          right: 64,
          bottom: 86,
          minHeight: 82,
          display: "flex",
          alignItems: "center",
          padding: "0 20px",
          background: verified > 0 ? theme.ink : theme.mutedSurface,
          color: verified > 0 ? theme.paper : theme.inkSoft,
          borderLeft: `5px solid ${theme.amber}`,
          opacity: Math.max(0.28, verified),
          fontSize: 24,
          lineHeight: 1.35,
          fontWeight: 800,
        }}
      >
        {evidenceLine}
      </div>
      <div style={{ position: "absolute", left: 64, bottom: 34, color: theme.inkSoft, fontSize: 17, letterSpacing: 1.5, fontWeight: 700 }}>
        {demoLabel}
      </div>
    </div>
  );
};
