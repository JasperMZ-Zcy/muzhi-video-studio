# Shotcraft 知识解释镜头参考（本地试验）

这是一套固定来源、可检索的**动作机制参考**，服务于杂志插画产线中的知识解释、院校官方信息、政策、证据与数据段。它固定来自`Vincentwei1021/video-shotcraft`的提交`5f047c7cfe10d6616fe59160a750fcfaea510b2e`；插件保存全部 157 张 Apache-2.0 文字镜头卡（589,159 bytes）及 214 个 gallery 样式的元数据。卡文本固定版本；预览链接指向官方实时Gallery，不冒充固定提交的视频证据。预览、音频、上游完整 Skill、demos、截图、依赖和工作台都没有下载或导入。

## 先选卡，再继续现有产线

在插件根目录运行下列只读命令。它不会安装命令行工具、下载媒体、发起渲染或调用供应商。

```text
python scripts/shotcraft_catalog.py validate
python scripts/shotcraft_catalog.py list --category data --limit 8
python scripts/shotcraft_catalog.py search 时间
python scripts/shotcraft_catalog.py search 里程碑
python scripts/shotcraft_catalog.py search 证据 --limit 8
python scripts/shotcraft_catalog.py select --ids depth-layer-moves,timeline-travel
python scripts/shotcraft_catalog.py read --ids depth-layer-moves,timeline-travel
```

`list`和`search`默认只返回至多 12 条紧凑结果，不把全库塞入当前上下文；`--limit 0`才完整列出。`select`返回故事板候选包，`read`才读取所选的 1—3 张本地文字卡。两者都不能等同于用户已批准、已生成或可发布。卡的固定提交来源、blob SHA、完整本地卡路径与 gallery 预览链接都在`full-index.json`中；预览链接只供按需查看，未下载、未本地验证，且是明确标记的官方 Gallery **实时预览，不是提交固定的视频证据**。

公开包另有通用源码入口`assets/shotcraft/templates/knowledge-pilot/`：`LayeredQuestionCard`、`TimelineProgress`、`ConditionComparison`分别对应三张初选卡。目录只含可移植源码、运行入口和`PUBLIC-REUSE-RECORD.json`，没有媒体、字体、音频、项目回执或历史哈希。它是本插件对动作机制的独立改编，不是上游 Remotion demo，也不证明上游其余变体、任何新项目的文字、字幕、声音或视觉都已通过。

任何卡要用于成片前，**当前执行助手**先阅读本项目`design.md`，再由助手在项目内记录`artifacts/shotcraft-style-contract.json`的`design_source`、`design_sha256`、`palette`、`font`、`safe_area`、`motion_intensity`六项。它是可复核的执行记录，不要求用户填写 JSON，也不新增一次用户审批。随后运行`python scripts/shotcraft_catalog.py validate-style --project <项目目录>`。脚本只核助手记录和`design.md`的实际哈希，**不假装能自动理解任意 Markdown**；缺记录或哈希漂移时，卡只能继续作为参考，不能回退套用库的样式，也不自动改设计锁、批准或旧片。

## 全库默认检索，六张已精选卡优先

需要把设计值交给本地组件时，继续读[风格参数适配](style-adaptation.md)。由执行助手将design.md落实为完整theme/props，再实际接进组件；不能只保存一份风格声明就声称外观已适配。

| 卡 | 用于解释 | 强度 | 本地实现状态 |
| --- | --- | --- | --- |
| `depth-layer-moves` | 用分层视差让证据卡、图解或资料页有纵深 | 中 | reference-only |
| `timeline-travel` | 里程碑、流程阶段或发展脉络 | 中高 | reference-only |
| `chart-live-moves` | 已核实数据的变化、构成或异常点 | 中高 | reference-only |
| `ring-diagram-annotation-reveal` | 抽象机制、关系和流程结构 | 中高 | reference-only |
| `research-card-stack-scroll` | 资料检索量级或多份可公开核验材料 | 中高 | reference-only |
| `list-reveal` | 低强度、可逐项阅读的规则、步骤或选项 | 低 | reference-only |

知识解释、院校官方信息、政策、证据和数据段默认先检索完整 157 卡库，而不是只把六张当备用效果。`depth-layer-moves`、`timeline-travel`、`chart-live-moves`是首轮已实际改编的三类；`list-reveal`保留为旁白铺垫或阅读段的低强度替代。选择必须服务口播理解，不能把每一句都硬做成动效，也不能缩短阅读时间；旧片和已批准导演板不因全库默认检索而改动。

## 必须保留的使用边界

- 卡只迁移动作结构，绝不复用原示例中的品牌、截图、占位数据、音效、音乐或产品结论；`chart-live-moves`、`timeline-travel`和`research-card-stack-scroll`必须替换为本项目已核验事实。
- 卡内的“参考实现”路径只说明上游位置。三张初选卡已有上述本地改编组件，但`implementation_template`仍保持`none`，避免把一次默认主题试验误报为所有上游变体或所有项目均生产通过；首次用于某条片仍须在该项目允许的渲染环境中留下真实文件、哈希和视听检查回执。
- 上游卡的示例曾在其语境下调校，不是本品牌、9:16、中文长文本或既有杂志插画视觉的验收。竖屏小字、快速扫读、频闪、失焦、字幕遮挡或与定稿音画不匹配时，放弃该卡或只保留更温和的机制。
- **样式优先级固定为：本项目`design.md` → 已确认的品牌风格 → 动效配方。** 主色、字体、纸张、插画处理、布局和字幕安全区都由本项目继承；禁止照搬上游英文 SaaS UI、库默认配色、占位图标和占位文案。
- 新知识片的比较、流程、因果、证据和数据段应主动检索这类机制，而不是只作偶尔点缀；但镜头必须服务理解，不能机械地每句都加，也不得缩短阅读时间。此倾向不改旧项目，当前试验仍只验证三镜头。
- 已审核的 Apache-2.0 文字卡与通用源码可按各自`release_scope`和`rights_review`公开分发；这只授权源码／文字参考，不表示任何媒体、截图、音频、具体项目输出或用户批准可以公开。所有项目输出仍以`project_output_approved: false`开始，须另行审查。

## 官方证据与有来源数据

官方网页、招生简章、政策条款、目录或表格数字必须沿用`official_evidence`或`sourced_chart`，并在导演前路线中记录`library_candidates`。镜头库只能帮助观众看懂，不能替代原始事实。

- 保留原文出处、链接或文件名、页码／条款／表格定位和核验状态；证据行与自己的解释行分层，不能把解释伪装成原文。
- 用真实页面或真实局部的可读裁切、放大、标注与停留，确保手机上能复核；不可重绘一个“像官方”的假截图、删轴夸大差异，或杜撰学校／政策／招生数据。
- 图表必须写清口径、年份、对象、单位与来源。暂未核验时可以在导演准备中标待查，不能制作成发布片的“演示数字”。
- 人物行为和环境变化才走`image_to_video`；准确文字和数字继续由真实材料承载。混合镜头先分清职责和接棒，不让生成画面覆盖证据。

## 渠道与费用没有变化

选卡不选择供应商。真正需要图生视频时，仍由当前项目选择：Google Flow只交首帧与提示词的手动包，WAN和MiniMax只走已配置的API；没有本次渠道选择或费用授权时停在本地故事板和素材包。镜头卡不改变既有声音、字幕、封面、37项否决、项目状态、生成台账或发布审批。

完整来源、哈希和资产记录在`assets/shotcraft/full-index.json`、`assets/shotcraft/full-cards/`、`assets/shotcraft/catalog.json`、`assets/shotcraft/asset-records/`和`assets/shotcraft/UPSTREAM.md`。卡的 Apache-2.0 副本在`assets/shotcraft/LICENSE`。
