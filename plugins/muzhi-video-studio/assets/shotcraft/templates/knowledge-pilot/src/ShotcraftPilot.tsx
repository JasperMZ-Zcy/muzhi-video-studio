import React from "react";
import { AbsoluteFill, Sequence } from "remotion";
import { ConditionComparison } from "./ConditionComparison";
import { LayeredQuestionCard } from "./LayeredQuestionCard";
import { TimelineProgress } from "./TimelineProgress";
import { PAPER_INK_THEME, PaperInkTheme } from "./theme";

export type ShotcraftPilotProps = {
  demoLabel: string;
  theme?: PaperInkTheme;
};

export const ShotcraftPilot: React.FC<ShotcraftPilotProps> = ({
  demoLabel,
  theme = PAPER_INK_THEME,
}) => {
  return (
    <AbsoluteFill>
      <Sequence from={0} durationInFrames={180}>
        <LayeredQuestionCard
          eyebrow="知识解释 / 先拆问题"
          title="先明确：你真正要判断什么？"
          lead="把模糊焦虑改写成能被比较、能被核对的问题。"
          prompts={["目标是什么？", "当前条件是什么？", "还缺哪一条证据？"]}
          demoLabel={demoLabel}
          theme={theme}
        />
      </Sequence>
      <Sequence from={180} durationInFrames={180}>
        <TimelineProgress
          eyebrow="知识解释 / 阶段推进"
          title="判断顺序，不靠跳步"
          steps={[
            { index: "01", title: "明确问题", detail: "把要做的选择写成一句可回答的话。" },
            { index: "02", title: "比较条件", detail: "把同一维度放在一起看，不混口径。" },
            { index: "03", title: "核对证据", detail: "回到能追溯的材料，再落下结论。" },
          ]}
          demoLabel={demoLabel}
          theme={theme}
        />
      </Sequence>
      <Sequence from={360} durationInFrames={180}>
        <ConditionComparison
          eyebrow="知识解释 / 条件对照"
          title="比较之前，先确认是不是同一条件"
          left={{ label: "条件 A", prompts: ["目标是否一致", "边界是否清楚", "证据来自哪里"] }}
          right={{ label: "条件 B", prompts: ["目标是否一致", "边界是否清楚", "证据来自哪里"] }}
          evidenceLine="示意：先做条件对照，再核对可追溯依据"
          demoLabel={demoLabel}
          theme={theme}
        />
      </Sequence>
    </AbsoluteFill>
  );
};
