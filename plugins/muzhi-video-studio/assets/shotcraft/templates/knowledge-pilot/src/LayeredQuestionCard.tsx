import React from "react";
import {
  Easing,
  interpolate,
  useCurrentFrame,
} from "remotion";
import { PAPER_INK_THEME, PaperInkTheme, paperBackground } from "./theme";

export type LayeredQuestionCardProps = {
  eyebrow: string;
  title: string;
  lead: string;
  prompts: string[];
  demoLabel: string;
  theme?: PaperInkTheme;
};

const enter = (frame: number, start: number, end: number): number =>
  interpolate(frame, [start, end], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });

/**
 * Ref-inspired adaptation of video-shotcraft's MultiplaneReal:
 * three reading layers travel at different, restrained rates. This component
 * uses native text and geometry only; it has no upstream assets or copied copy.
 */
export const LayeredQuestionCard: React.FC<LayeredQuestionCardProps> = ({
  eyebrow,
  title,
  lead,
  prompts,
  demoLabel,
  theme = PAPER_INK_THEME,
}) => {
  const frame = useCurrentFrame();
  const safePrompts = prompts.slice(0, 3);
  const backgroundDrift = interpolate(frame, [0, 118], [26, -18], {
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });
  const middleDrift = interpolate(frame, [0, 118], [42, -34], {
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });
  const foregroundDrift = interpolate(frame, [0, 118], [66, -58], {
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });
  const titleIn = enter(frame, 5, 22);
  const titleY = interpolate(titleIn, [0, 1], [26, 0]);
  const questionDraw = enter(frame, 16, 42);

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        position: "relative",
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
          inset: -60,
          translate: `${backgroundDrift}px 0px`,
          border: `1px solid ${theme.rule}`,
          background: theme.backgroundOverlay,
        }}
      />
      <div
        style={{
          position: "absolute",
          width: 620,
          height: 820,
          left: 92,
          top: 280,
          translate: `${middleDrift}px 0px`,
          rotate: "-3deg",
          background: theme.panelSurface,
          border: `1px solid ${theme.rule}`,
          boxShadow: theme.shadow,
        }}
      />
      <div
        style={{
          position: "absolute",
          inset: "92px 64px 74px",
          display: "flex",
          flexDirection: "column",
          opacity: titleIn,
          translate: `0px ${titleY}px`,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            color: theme.inkSoft,
            fontSize: 19,
            fontWeight: 700,
            letterSpacing: 2,
          }}
        >
          <span style={{ width: 26, height: 2, background: theme.amber }} />
          {eyebrow}
        </div>
        <div
          style={{
            marginTop: 28,
            maxWidth: 560,
            fontSize: 56,
            lineHeight: 1.2,
            fontWeight: 800,
            letterSpacing: -2,
          }}
        >
          {title}
        </div>
        <div
          style={{
            marginTop: 24,
            maxWidth: 530,
            fontSize: 28,
            lineHeight: 1.55,
            color: theme.inkSoft,
            fontWeight: 600,
          }}
        >
          {lead}
        </div>

        <div
          style={{
            position: "relative",
            marginTop: 48,
            minHeight: 346,
            translate: `${foregroundDrift}px 0px`,
          }}
        >
          <div
            style={{
              position: "absolute",
              left: 0,
              top: 0,
              color: theme.amber,
              fontSize: 164,
              lineHeight: 0.9,
              fontWeight: 800,
              opacity: 0.2 + questionDraw * 0.8,
            }}
          >
            ?
          </div>
          <div
            style={{
              position: "absolute",
              left: 112,
              top: 30,
              right: 0,
              height: 3,
              background: theme.amber,
              scale: `${questionDraw} 1`,
              transformOrigin: "left center",
            }}
          />
          <div
            style={{
              position: "absolute",
              left: 112,
              top: 64,
              right: 16,
              display: "flex",
              flexDirection: "column",
              gap: 18,
            }}
          >
            {safePrompts.map((prompt, index) => {
              const promptIn = enter(frame, 32 + index * 15, 47 + index * 15);
              const promptX = interpolate(promptIn, [0, 1], [54, 0]);
              return (
                <div
                  key={prompt}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 16,
                    opacity: promptIn,
                    translate: `${promptX}px 0px`,
                    minHeight: 70,
                    padding: "0 22px",
                    background: theme.promptSurface,
                    borderLeft: `4px solid ${index === 1 ? theme.amber : theme.rule}`,
                    fontSize: 29,
                    fontWeight: 800,
                  }}
                >
                  <span style={{ color: theme.amber, fontSize: 18 }}>0{index + 1}</span>
                  <span>{prompt}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
      <div
        style={{
          position: "absolute",
          left: 64,
          bottom: 34,
          color: theme.inkSoft,
          fontSize: 17,
          letterSpacing: 1.5,
          fontWeight: 700,
        }}
      >
        {demoLabel}
      </div>
    </div>
  );
};
