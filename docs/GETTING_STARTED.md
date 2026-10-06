# 快速开始

这份说明从一台没有牧之内部项目的新机器出发。你可以先用内容入口讨论一条片，也可以直接拿确认稿和本人录音进入制作。想先试命令，可让插件读懂包内短例、给出真实候选与计划状态。**能检索、能规划，不等于已经渲染。**

## 需要准备什么

- 已安装并能使用插件的 Codex，以及 Python 3.10 或更新版本；只读检索和导演前计划检查使用 Python 标准库。完整的主画面调用预检还需要 Node.js 与本包锁定的 TypeScript 检查依赖，可在插件目录运行 `npm ci --ignore-scripts` 后使用；这一步只装本地检查工具，不装模型或浏览器。
- 你自己有权处理的文稿、录音、图片、视频和品牌资料。讨论选题与短教学例不需要个人录音；正式有声制作需要本人录音。
- 真要制作媒体，再准备可用的 React/Remotion 工程及所需依赖；要检查视频时长和音轨，准备 `ffprobe`，完整解码、M4A转WAV及部分音视频工作还需 `ffmpeg`。若选择本地语音转写，另需自己已安装的可选转写依赖和已存在的本地模型快照；插件不会自动下载浏览器、模型或供应商环境。

安装命令：

```bash
codex plugin marketplace add JasperMZ-Zcy/muzhi-video-studio
codex plugin add muzhi-video-studio@muzhi-video-studio
```

已有本仓库Marketplace时，先刷新来源再安装当前版本：

```bash
codex plugin marketplace upgrade muzhi-video-studio
codex plugin add muzhi-video-studio@muzhi-video-studio
codex plugin list --json
```

`marketplace upgrade` 更新来源快照，`plugin add` 从快照安装；实际Marketplace名字不同则先用 `codex plugin marketplace list` 看本机名称。新开任务再调用插件，旧聊天不会自动改用新技能；`list --json` 核实际安装、启用与版本。以上语法按[Codex官方命令说明](https://learn.chatgpt.com/docs/developer-commands)和本机CLI帮助核过。下文 `<PLUGIN_ROOT>` 指实际包含 `.codex-plugin`、`scripts`、`assets` 的插件根：仓库源码中是 `plugins/muzhi-video-studio`，Codex 安装缓存中通常是该插件名下的某个版本目录。`<PROJECT_ROOT>` 指你明确授权处理的项目目录。它们是占位符，不是要照字面创建的文件夹。

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

只有想法时，先从内容入口开始：

> 用牧之远见视频创作工作室的内容入口，帮我讨论这条片讲给谁、放在哪个平台、观点与口吻怎么定。先给一个有依据的推荐方向；我会继续提意见，确认稿前不进入视频制作。

已有确认稿与本人录音时，可以对 Codex 说：

> 用视频创作工作室制作这个项目。目录在 `<PROJECT_ROOT>`。这份是确认稿，这份是我有权使用的本人录音；保留原件，明确重录或口误才在副本清理，给我试听候选音轨。我确认最终声音后，请你校对实际字幕和时码，再告诉我观众最容易误解哪几句，为每镜准备能看能改的导演板。图生与配乐方法按这条片来选，外部费用和发布另说。

录音若是M4A，`narration_track.py decode-local` 用现有FFmpeg转成新的标准PCM16 WAV副本，原文件和SHA保留；已有可读的PCM WAV则从原件复制处理。若WAV容器不被本机工具识别，先另作标准PCM16副本并保留原件，不改写旧文件。对明显重录、口误、过长空白可按样本区间清理副本，不确定是口误还是临场新表达时，标出差异由你决定。候选音轨要经你真实试听确认，制作助手才可据此转写并逐字、逐时码校对SRT；机器识别文本和稿件差异摘要都不能替代听音。已锁旧片不自动重剪。具体本机转写入口、可用性和缺能力时的停点见[渠道与工具](PLATFORMS.md)。

可选本地ASR只使用你为**这条片**指定的已存在模型快照；先查就绪，再在候选音轨真实获试听确认后转写。以下命令供检查，项目目录、模型位置和候选路径须换成自己的真实值；平时可以直接让Codex执行并解释结果：

```bash
python "<PLUGIN_ROOT>/scripts/narration_track.py" asr-status --project "<PROJECT_ROOT>" --model-dir "<EXISTING_LOCAL_SNAPSHOT>"
python "<PLUGIN_ROOT>/scripts/narration_track.py" transcribe-local --project "<PROJECT_ROOT>" --candidate audio/final-candidate.wav --out-dir artifacts/asr-v1 --model-dir "<EXISTING_LOCAL_SNAPSHOT>"
```

第二条只接受由本包准备、并已绑定本人试听确认的候选音轨；输出到项目内**新目录**，只给转写草稿和来源回执。缺 `faster-whisper`、模型快照或真实确认就停在相应缺口，不下载模型、不调用私人工作区工具或收费云端；`asr-status` 的 `ready` 也不证明模型质量与字幕准确。

新项目先选一款主风格：`editorial-illustration`（杂志插画）或 `archival-current-collage`（档案电流拼贴）。它只锁**这条片**的视觉方向，不决定模型或供应商。已有项目先读状态、设计和已绑定媒体，不因换插件就重新选风格；下载者没有原项目的有效备份或外部封存清单时，不把普通旧目录当成已经通过新版审核。

每段画面至少要说清三件事：原话要求观众理解什么；由哪份真实资料、准确字图或有权艺术层承担；进入、变化、读停和退出怎样落在口播时码上。原页小字可以证明页面身份，但观众必须读到完整条件或数字时，还需要准确的近读设计。没证据的条件保持“未知”，不同分母的数据不要画成同一趋势。

在正式批量前，计划须经当前检索/选弃核对，所选资源逐段 `resolve` 检查源码、props、截图格式、源像素读窗、输入哈希与主画面调用。同版HTML导演板让你按镜号看原话、局部声音、接近成片的真实关键帧和修改处；静图看不出连续行为时给短预演或明确待完成。意见修改后，请你确认这一版整体才批量，不用给每张图反复点批准。渲染后再核真实输出身份、关键帧、连续动作、手机尺度和音画；片前确认、成片认可和正式发布是不同关口。[质量与验收](QUALITY.md)解释如何判读。

每条片若确需图生视频，先选这次用本地、已配置云能力、手动平台或其他确实可用的方法；纯资料页和原生动画不为图生选渠道。配乐每条片也先选代码创作、已核AI能力、你提供且有权使用的素材，或不配。代码谱的旋律、节奏、分段与有限音色由制作助手按本片写，再和真实口播、画面一起给你听；你判断是否贴片、遮声即可，不用提供BPM。渠道和配乐的选择都不自动授予费用或账号操作权限。

## 常见停点

| 看到的情况 | 应怎样处理 |
| --- | --- |
| 查库零结果 | 换成要表现的关系和动作词再查，并保留真实零命中回执；不要因此断言库没有能力。 |
| `passed: true`，但 `actual_media_ready: false` | 只有计划或静态资料，尚无同版连续媒体；不能交付成片。 |
| 来源页分辨率不够 | 依法取得更清晰原件，或缩小本镜要读的范围；不能无限放大模糊字。 |
| 缺 props、图片或源码哈希漂移 | 渲染前补齐并重新锁输入；不要把旧 MP4 事后绑到新源码。 |
| 候选音轨未试听确认，或SRT与实际声音有差异 | 保留原件，先处理该句与音轨选择；制作助手再听音校对字幕。不能填假确认让正式导演过门。 |
| 本片尚未选图生渠道或配乐方法 | 只在本片真正需要的阶段询问；无图生段不问图生渠道。不要套上一片的选择或旧H3默认。 |
| 没有可用的视频供应商 | 先做已授权的原生动效或手动素材包，说明缺什么；不假装生成已完成。 |
| 费用、账号或发布权限未定 | 停止相应外部动作，先说清对象、代价和需要的决定。 |

成本留额与供应商选择按项目走原台账；本插件不会购买额度，也不能替你判断第三方素材是否可商用。[渠道与工具](PLATFORMS.md)、[安全说明](SECURITY.md)和[知识解释镜头库](SHOT_LIBRARY.md)各管一部分，不必一次学完所有命令。
