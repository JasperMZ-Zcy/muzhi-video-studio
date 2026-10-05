# 快速开始

这份说明从一台没有牧之内部项目的新机器出发。先让插件读懂一个短例、给出真实候选与计划状态，再决定是否接入自己的录音和素材。**能检索、能规划，不等于已经渲染。**

## 需要准备什么

- 已安装并能使用插件的 Codex，以及 Python 3.10 或更新版本；只读检索和导演前计划检查使用 Python 标准库。完整的主画面调用预检还需要 Node.js 与本包锁定的 TypeScript 检查依赖，可在插件目录运行 `npm ci --ignore-scripts` 后使用；这一步只装本地检查工具，不装模型或浏览器。
- 你自己有权处理的文稿、录音、图片、视频和品牌资料。短教学例不需要这些个人素材。
- 真要制作媒体，再准备可用的 React/Remotion 工程及所需依赖；要检查视频时长和音轨，准备 `ffprobe`，完整解码检查还需 `ffmpeg`。插件不会自动下载浏览器、模型或供应商环境。

安装命令：

```bash
codex plugin marketplace add JasperMZ-Zcy/muzhi-video-studio
codex plugin add muzhi-video-studio@muzhi-video-studio
```

新开任务再调用插件。`codex plugin list --json` 可核是否已安装、启用及版本；新任务才会读取新版 skill。下文 `<PLUGIN_ROOT>` 指实际包含 `.codex-plugin`、`scripts`、`assets` 的插件根：仓库源码中是 `plugins/muzhi-video-studio`，Codex 安装缓存中通常是该插件名下的某个版本目录。`<PROJECT_ROOT>` 指你明确授权处理的项目目录。它们是占位符，不是要照字面创建的文件夹。

## 不用素材，先跑一遍最小例

发行包内的 `assets/examples/studio-authored-minimal` 是四秒的**无声教学脚本和源码**。文案只说“条件未核完，就先标待定”；没有学校原件、本人录音或已制作的 MP4。先在 `<PLUGIN_ROOT>` 运行 `npm ci --ignore-scripts` 准备本地代码调用检查，再执行下面几项只读检查：

```bash
cd "<PLUGIN_ROOT>"
npm ci --ignore-scripts

python "<PLUGIN_ROOT>/scripts/resource_handoff.py" search-receipt 条件 待定 --per-source 1
python "<PLUGIN_ROOT>/scripts/resource_handoff.py" read --ids shotcraft_pilot:ConditionComparison

python "<PLUGIN_ROOT>/scripts/motion_plan.py" validate --project "<PLUGIN_ROOT>/assets/examples/studio-authored-minimal" --plan "<PLUGIN_ROOT>/assets/examples/studio-authored-minimal/motion-plan.json" --stage pre-director
python "<PLUGIN_ROOT>/scripts/production_runner.py" check --workflow studio --stage preview --project "<PLUGIN_ROOT>/assets/examples/studio-authored-minimal" --plan motion-plan.json
```

当前公开索引下，第一条会返回 `shotcraft_pilot:ConditionComparison`；第二条正好读这个命中项的源码身份、输入和使用边界。若以后索引变化，以当次真实回执里的 ID 为准，不照抄一个未命中的名字。计划校验会检查原文、输入哈希、每段义务与选弃记录。最后一条即使返回 `passed: true`，也应同时看到 `completion_state: plan_only`、`actual_media_ready: false`、`delivery_ready: false`。这是正确结果：短例没有渲染媒体，不能把结构通过当成片。若源码包、检索索引或例子哈希不匹配，应停下来查具体缺项，不靠修改通过字段继续。

这些命令不会访问供应商、提交付费任务、渲染视频或发布内容。想核可改的组件，可让 Codex 在 [镜头库说明](SHOT_LIBRARY.md) 中选择一个原件，先读完整输入合同和反例，再决定是否在你自己的项目里改编。

## 把自己的内容接进来

可以直接对 Codex 说：

> 用视频创作工作室继续这个项目。目录在 `<PROJECT_ROOT>`。这份是定稿，这份是我有权使用的录音；先保护已经通过的声音和镜头，再读完整文稿，告诉我观众最容易误解哪几句。请为最难的一段选真实来源、可改的动作机制和合适的风格。没有我的确认，不调用付费工具或发布。

新项目先选一款主风格：`editorial-illustration`（杂志插画）或 `archival-current-collage`（档案电流拼贴）。它只锁**这条片**的视觉方向，不决定模型或供应商。已有项目先读状态、设计和已绑定媒体，不因换插件就重新选风格。

每段画面至少要说清三件事：原话要求观众理解什么；由哪份真实资料、准确字图或有权艺术层承担；进入、变化、读停和退出怎样落在口播时码上。原页小字可以证明页面身份，但观众必须读到完整条件或数字时，还需要准确的近读设计。没证据的条件保持“未知”，不同分母的数据不要画成同一趋势。

在正式渲染前，计划须经当前检索/选弃核对，所选资源逐段 `resolve` 检查源码、props、截图格式、源像素读窗、输入哈希与主画面调用。渲染后再核真实输出身份、关键帧、连续动作、手机尺度和音画。逐段预览通过、人工确认和正式发布是不同关口；[质量与验收](QUALITY.md)解释如何判读。

## 常见停点

| 看到的情况 | 应怎样处理 |
| --- | --- |
| 查库零结果 | 换成要表现的关系和动作词再查，并保留真实零命中回执；不要因此断言库没有能力。 |
| `passed: true`，但 `actual_media_ready: false` | 只有计划或静态资料，尚无同版连续媒体；不能交付成片。 |
| 来源页分辨率不够 | 依法取得更清晰原件，或缩小本镜要读的范围；不能无限放大模糊字。 |
| 缺 props、图片或源码哈希漂移 | 渲染前补齐并重新锁输入；不要把旧 MP4 事后绑到新源码。 |
| 没有可用的视频供应商 | 先做已授权的原生动效或手动素材包，说明缺什么；不假装生成已完成。 |
| 费用、账号或发布权限未定 | 停止相应外部动作，先说清对象、代价和需要的决定。 |

成本留额与供应商选择按项目走原台账；本插件不会购买额度，也不能替你判断第三方素材是否可商用。[渠道与工具](PLATFORMS.md)、[安全说明](SECURITY.md)和[知识解释镜头库](SHOT_LIBRARY.md)各管一部分，不必一次学完所有命令。
