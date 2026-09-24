import React from "react";
import { Composition } from "remotion";
import { ShotcraftPilot, ShotcraftPilotProps } from "./ShotcraftPilot";
import { PAPER_INK_THEME } from "./theme";

export const ShotcraftSampleRoot: React.FC = () => {
  return (
    <Composition
      id="ShotcraftPilot-9x16"
      component={ShotcraftPilot}
      durationInFrames={540}
      fps={30}
      width={720}
      height={1280}
      defaultProps={{
        demoLabel: "镜头融合测试 · 示意",
        theme: PAPER_INK_THEME,
      } satisfies ShotcraftPilotProps}
    />
  );
};
