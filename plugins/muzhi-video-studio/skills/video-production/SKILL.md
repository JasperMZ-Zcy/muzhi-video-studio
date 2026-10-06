---
name: video-production
description: 牧之远见·视频创作工作室的导演与制作入口。用于确认稿后的本人录音、SRT、镜头导演、逐镜审核、制作和成片检查；也承接已锁定视频续作与能力对照。单纯选题和口播文案讨论进入 content-planning。
---

# 视频创作工作室

这是同一工作室的「导演与制作」主入口。只讨论选题、观点、口吻或口播稿时进入 `../content-planning/SKILL.md`，不在制作入口重写确认稿。已有项目读取自己的`HANDOFF.md`、锁定文稿/录音、`design.md`和真实文件身份；已锁定的杂志正式片按原`magazine-production`兼容入口与质量门续作。状态询问或纯创意讨论不初始化制作项目，已确认决定不重复问。

新片确认稿后读[本人录音与SRT](references/narration-and-srt.md)。`scripts/narration_track.py`保原声、精确裁剪新副本；牧之试听确认最终音轨后，可选本地离线ASR草稿，再由制作助手逐字及时码校对SRT并锁同版。模糊口误先提出，不替用户删词；不默认变速、改音色或TTS补词。新片正式`studio storyboard/batch/master`会核确认稿、最终音轨和SRT的同一锁；无真实新片录音时不剪旧声轨。已核旧片沿原版本和有效备份续作；未知或重绑的v2计划不能借旧标签豁免同版门。

## 第一步：确认本片风格

使用插件根目录`assets/style-catalog.json`及`scripts/style_registry.py catalog`查看当前风格。先运行`status --project <项目目录>`：有真实风格锁按锁继续；仅有`artifacts/editorial-plugin-state.json`文件，不能证明旧作身份，须核里面已有工作与输入绑定。没有锁时，结合口播任务、受众理解难点和已有素材推荐一种；用户明确指定的优先。一次只为本片选一种主风格，可按镜头需要混用证据/数据/真实动作表达路线，不能把风格和镜头路线混为一谈。

用`select --project <项目目录> --style <ID> --mode production|trial --reason <本片理由> --new-project`保存新项目风格锁；已有项目无插件状态也**不等于新项目**，先核已有资产/设计/审批，再改用`--existing-project-reviewed`明确接管。已锁风格需改变时，先说明受影响镜头和原资产，再用`revise --reason`留下旧选择历史；不能悄悄重选或继承上一片临时偏好。新增风格先登记状态、入口、适用边界和独立验收，不能只加一个名字。

当前目录有两种选项：

- **杂志插画** `editorial-illustration`：成熟路径。已锁定的杂志正式片或用户明确选择该专门产线时进入`../magazine-production/SKILL.md`；原37项否决、原批准封面、本人声音和已有锁定版本完整保留。普通新片仍从本入口导演制作。
- **档案电流拼贴** `archival-current-collage`：有公开风格试镜，可作为新项目的一个选择。进入[拼贴风格参考](references/archival-current-collage.md)和[共用质量底线](references/shared-quality.md)；试镜中的一处关系线偏早，正式片逐镜验收。

其他风格未入目录时，可以先按用户选择建立项目级实验设计和独立试镜，不把实验当作可用的正式产线，也不修改旧项目。用户可随时改变单片渠道；模型平台不是风格。风格目录允许`trial_only`与`production_ready`，前者不能作为正式制作选择。

## 稳定的生产骨架

策划入口交确认稿后才启动新片正式导演。沿同一`motion_plan`和`artifacts/director-storyboard.json`逐镜展示原句/时码、可听局部原声、实际近成片关键帧、焦点变化与阅读窗；静读镜看完整读点，动态义务用必要短预演或明列缺口。逐镜反馈改到同一版，版本获用户确认后才批量，不另造第二镜头计划。到片前审核时读[逐镜同版审核](references/director-review.md)。

按[共用流程](references/shared-pipeline.md)推进：内容入口确认稿 → 本人最终录音与校对SRT → 导演理解 → 本片`design.md` → 导演前镜头路线 → 带真实关键帧和局部声的同版导演板 → 用户逐镜提意见、确认整版 → 最难一段的真实样片 → 批量镜头 → 音画合成 → 质检与交付。只读当前阶段必要参考；旧项目已完成且锁定的阶段不追溯重跑。局部返工只影响对应资产，原素材、哈希和历史版本保留。无原声的教学试验只能标作者屏幕时间，不冒正式有声样片。

新稿导演准备同时读[机制选择与完整表达](references/mechanism-selection.md)。从原句要改变观众哪种认识开始，先分真实来源、准确字图、人物/器物动作的责任，再检索本包候选。`resource_handoff.py search-receipt`记录实际查询和结果，`read`给原件与拒用边界；目录命中不是已读、已适配或已执行。当前公开包只登记Shotcraft文字参考、三件通用试镜部件及七个原创关系机制，不假装有使用者的私有资料库、Agent Motion分析库或214个渲染器。

新v2计划先运行 `scripts/motion_plan.py validate --stage pre-director`，再按段 `scripts/resource_handoff.py resolve` 核项目输入、截图/props与主画面调用。`scripts/production_runner.py check --workflow studio --stage preview`把无媒体的`plan_only`与已绑定真实预览分开；`passed`仅对应当前检查，不等于交付或发布。需要源码调用预检时，先在插件目录`npm ci --ignore-scripts`安装锁定的本地检查依赖，不下载模型或浏览器。包内短例位于`assets/examples/studio-authored-minimal`，应在新目录实际读回；个人录音、正式文案与真实媒体要用户另给。

导演板**之前**把口播段落分到`image_to_video`、`native_mg`、`official_evidence`、`sourced_chart`、`vox_layered_broll`、`real_media`或`hybrid`。实际需要真实人物/器物动作才进入图生视频；官方学校信息、数字和图表用可核来源和本地准确排版，不能让模型画伪字。新片解释镜头先核外部 Agent Motion 是否已安装且有本项目使用范围依据；具备条件时按[Agent Motion 接入合同](references/agent-motion.md)读索引、选例并留下可见动作的样片证据。尚未安装、缺使用依据或不适合时，说明本片不启用它，继续用 Shotcraft 或原创本地动效，不让可选后端卡住主产线；用户明确只要该后端时才停在相应缺口。它不新增风格、不代替`visual_route`或图生供应商，旧项目不自动改动。Shotcraft镜头库按语义检索，改造成所选风格，不让解释段退化成截图或PPT。每镜写明进入、接触/变化、结果、退出、衔接和真实口播时码。

只有本片选`image_to_video`或`hybrid+uses_image_to_video`时，用`scripts/provider_router.py status/select`记录本片明确渠道；非图生镜头不触询问。新片没有H3自动默认，旧已选渠道、任务与费用仍按项目记录。可选本地ComfyUI/MiniMax-H3、WAN/MiniMax云API、Google Flow手动首帧/提示词包，或用户新指定平台。切换只影响尚未提交的镜头，不重交已付费任务。渠道输出统一为本地镜头文件、实际时长、任务/素材哈希和质检状态后再合成。具体执行复用`../magazine-production/references/video-provider-routing.md`，其中渠道合同可跨风格使用，杂志独有画风要求不跨风格继承。本机H3仅在实际选用时读`../magazine-production/references/local-h3.md`并先预检，不保证环境或速度。

## 验收与交付

背景音乐先按[每片配乐方法](references/music-planning.md)选择`code_local`、已核可用AI能力、使用者提供有权素材或`none`，`scripts/music_method.py`只存真实本片选择。代码路线由制作助手按这片口播与镜头写谱，用`scripts/code_music.py render`生成新WAV；算法音色有局限，不能把旧示例的旋律、速度或长度当通用模板。方法记录不证明AI账号、费用授权或音乐听感，最终要在实际声画样段和整片里听。

生成文件不等于审核通过。每个真实动态样片看首/中/尾及因果动作；静帧、光流补时和整图呼吸不算原生动态。按本片风格参考与共用质量底线分别做视觉和技术验收，记录实际媒体、版本和问题；正式对外发布还需独立复核、真实用户批准和账号权限。原始录音、定稿、字幕和被认可封面不擅改。新音乐、付费生成、账号操作和发布按本任务授权边界执行，不因为插件可调用就自动做。

交付说清哪种风格、哪段实际动态通过、哪里仍是试验、实际平台任务与费用、可预览版本以及唯一下一步。未来新增风格只改风格目录与对应参考/测试，不改其他风格已经锁定的标准。
