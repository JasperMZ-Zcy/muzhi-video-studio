# 牧之远见·视频创作工作室｜快速开始

## 先按你的情况沟通

我们提供了一套可以直接安装和调用的插件程序，最终效果需要根据你的内容、声音、审美、预算和可用工具调整。可以先告诉Codex你手里已有录音还是已有视频、想做什么感觉、哪些地方不能动，再确定适合本项目的工作顺序。

先用一小段试人物、动作、字幕和配乐，满意后再做全片。工作序列允许按实际情况调整，文件身份、声音和必要的画面检查仍需完成。示例作品与数据只反映我们的实际制作，不是安装后的效果保证。

本插件适合“已有内容制作能力，希望把视频生产过程变得可检查、可续做、可控范围”的 Codex 用户。它不替代你的模型订阅、视频工具或云账号。

## 运行环境

- Codex 已安装并可以使用插件；
- Python 3.10 或更高版本。插件自身 Python 脚本只使用标准库；
- 需要执行真实媒体规格／完整解码审核时，机器还需要可用的 `ffprobe`，以及可选的 `ffmpeg`；
- 你有权使用本项目的录音、图片、视频、品牌规范和发布资料。

不会自动安装 ffmpeg、配置供应商凭证、创建账号或购买额度。

## 安装与新任务接入

```bash
codex plugin marketplace add JasperMZ-Zcy/muzhi-video-studio
codex plugin add muzhi-video-studio@muzhi-video-studio
```

安装完成后新开任务。不要期待安装把正在进行的对话变成新工作流；插件中的 skills 会在新任务中按请求匹配。

### 从零开始

可以这样说：

```text
用视频创作工作室制作一条不露脸知识口播。先推荐适合本片的风格；
也可以按我的选择使用“杂志插画”或“档案电流拼贴”。
项目目录是 <PROJECT_ROOT>；我会提供经过授权的录音、文案和品牌资料。
先给出最小计划，确认图生渠道和本轮预算边界。
```

### 接手旧项目

可以这样说：

```text
继续 <PROJECT_ROOT> 里的视频项目。
先读 HANDOFF.md、已锁定的设计和素材、插件状态与风格状态；
保留已通过的录音、字幕、镜头和时间线，只处理第一个真实未完成阶段。
```

项目内状态由脚本管理，而不是由文件名猜测。先查看状态不会创建文件：

```bash
python <PLUGIN_ROOT>/scripts/project_state.py status --project <PROJECT_ROOT>
python <PLUGIN_ROOT>/scripts/style_registry.py catalog
python <PLUGIN_ROOT>/scripts/style_registry.py status --project <PROJECT_ROOT>
python <PLUGIN_ROOT>/scripts/provider_router.py status --project <PROJECT_ROOT>
python <PLUGIN_ROOT>/scripts/generation_ledger.py status --project <PROJECT_ROOT>
```

`<PLUGIN_ROOT>` 表示安装后仓库中的 `plugins/muzhi-video-studio` 目录；`<PROJECT_ROOT>` 是你明确授权处理的项目目录。它们是可移植占位符，不是要原样创建的目录名。

新项目先选择一种主风格：`editorial-illustration`（杂志插画）或 `archival-current-collage`（档案电流拼贴）。风格会锁在当前项目中，不跟图生渠道绑在一起。旧杂志项目按原有状态续作；即使没有插件状态，只要目录里已有项目材料，也要先核对资产与设计，不能当作空白新片重选画风。档案电流拼贴通过的是风格层试镜，正式片的每个动作和文字仍需逐镜检查；公开展示的那段试镜有一处关系线偏早，不把它当正式镜头范本。

## 选定风格，再安排每段画面

导演板前，把已确认的口播、现有证据和本片设计资料交给 Codex。它会按段落判断观众需要看见什么。

- 人物动作和环境变化可以走图生视频。
- 比较、步骤、因果和概念解释可以检索知识动效配方。
- 院校招生简章、政策条款和精确数字用真实出处、局部放大和高亮来讲，不能交给图生模型重写。

图生画面和知识动效都应跟随当前项目的 `design.md`。它们共用本片选定的视觉语言、色板、字体、材质、构图、字幕槽和运动节奏；杂志插画的独有画风不会强加给档案电流拼贴。设计有改动时，只复核受影响镜头，已锁定的录音、素材和通过的内容继续保留。

镜头库提供 157 张配方与 214 种样式线索，方便少从零开始想镜头。它不代替导演判断，也不保证任何项目自动适配。详细说明见[知识解释镜头库](SHOT_LIBRARY.md)。

## 推荐的最小流程

![工作流管线示意](assets/pipeline.svg)

1. 明确本轮目标、可修改范围、必须保留项、预算和是否允许公开发布。
2. 读取现有状态、风格锁与对应质量合同；新片先选风格，已有项目从第一个未完成阶段继续。
3. 为未提交的图生视频选择渠道，并把真实授权范围记录在项目里。
4. 生成前用成本台账 `plan` 和 `reserve`，外部平台返回任务 ID 后再 `attach`。
5. 回收文件先核 SHA、时长、画幅、帧率与音轨，再进入统一剪辑合同。
6. 完成所需阶段的真实检查与人工视听审核后，交付当前授权范围内的产物。

## 成本台账的最小示例

以下命令只写入当前项目的本地台账；它不会调用供应商：

```bash
python <PLUGIN_ROOT>/scripts/generation_ledger.py plan \
  --project <PROJECT_ROOT> --kind image --key shot-01 \
  --input-file prompts/shot-01.txt --input-file refs/shot-01.png \
  --provider <PROVIDER> --model <MODEL> \
  --estimated-cost <ESTIMATE> --budget <APPROVED_BUDGET> --unit credits

python <PLUGIN_ROOT>/scripts/generation_ledger.py reserve \
  --project <PROJECT_ROOT> --kind image --key shot-01 \
  --input-file prompts/shot-01.txt --input-file refs/shot-01.png \
  --provider <PROVIDER> --model <MODEL> \
  --estimated-cost <ESTIMATE> --budget <APPROVED_BUDGET> --unit credits \
  --quote "<用户实际授权原话>"
```

只有返回新 reservation 时，外部调用才属于本轮允许的工作。对已完成的相同输入，脚本会要求复用；对已挂起或未知但已有外部 job ID 的任务，它会要求先续查；对失败任务，重试需要 `--retry-quote`。费用未知必须保持未知，不能为了让预算通过填成零。

## 常见停点

| 情况 | 应做什么 |
| --- | --- |
| 没有可用的视频供应商 | 准备已授权的首帧／提示词／手动包，报告具体缺项；不假装已生成。 |
| 预算不足或需要更多付费变体 | 停止新增留额，说明现有占用与所需追加授权。 |
| 旧输出文件哈希变化 | 不再把它当作可复用成功输出；重新核文件来源，并在需要重新生成时记录明确重试授权。 |
| 只改封面 | 只影响 covers/release；不重跑音频、字幕、镜头或整片导出。 |
| 已定时内容 | `scheduled` 不等于 `published`；本地封面交付不代表已替换平台上的定时帖。 |

接下来请阅读 [渠道与交付合同](PLATFORMS.md) 和 [质量与验收](QUALITY.md)。
