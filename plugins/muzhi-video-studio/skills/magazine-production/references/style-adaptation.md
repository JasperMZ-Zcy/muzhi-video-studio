# 将本片设计落实为组件参数

在导演前置阶段共用风格意图，导演板阶段落实design.md；正式组件与图生首帧必须派生自同一份设计。下面是助手内部执行，不让用户填写JSON、不添加新审批环节。

1. 阅读本片design.md及必要的已确认视觉参考，解释色板、字体、材质、构图、字幕槽与动作强度；不能默认套样片纸墨。
2. 记录原有`artifacts/shotcraft-style-contract.json`供来源核验。另在同项目保存结构化样式参数，含下列字段；两份记录引用同一design哈希。
3. `python scripts/shotcraft_style.py validate --project <项目> --params <参数JSON>`核完整性；再以`write`生成本项目`style-adapter/shotcraft-remotion-style.json`。新版本可用`--output style-adapter/<本次版本>.json`，不覆盖旧输出。
4. 将输出`component_props.theme`实际传给三个试验组件或适配后的上游组件。`component_props.style`只是纹理、安全区与动作边界数据，执行助手必须在真实组合层落实，不能以导出JSON代替视觉实现。
5. 图生首帧/提示词同步采用本片人物、色板、材质、构图与光影；生成模型不负责准确中文/政策/数字。两条路线在完整有声动态分镜中检查风格与口播节拍，不到最后才统一调色。

## 结构化参数

- `schema_version: 1`、`design_source: "design.md"`、`design_sha256`（真实文件SHA-256）。
- `palette`对象：`paper,paperDeep,ink,inkSoft,amber,amberSoft,rule`用#RRGGBB；`backgroundOverlay,panelSurface,promptSurface,mutedSurface,shadow`为明确CSS值。字段名称是兼容现有组件的语义槽位，不要求真的用琥珀或纸面。
- `font: {"family": "本项目字体"}`，核本地可用性与字形；字体文件不随库附送。
- `texture: {"kind": "本项目材质"}`，可选正整数`line_spacing_px`。
- `safe_area`对象：整数`width,height,left,right,top,bottom,subtitle_reserve_bottom`；非负边距且必须留有效区域。
- `motion`对象：`intensity`为low/medium/high，`allowed_mechanisms`非空字符串列表，`forbidden_mechanisms`可空，二者不能冲突。

脚本不解析任意Markdown、不自动选美术风格、不渲染。缺字段、design哈希变化、路径逃逸、已有不同输出都拒绝；重复同内容返回already-current。本试验组件只实测720×1280默认主题，正式1080版、其他长文本、字幕槽和布局须按本片设计适配验证，不能把改色当作全风格完成。

镜头卡中的参考代码不一定接受此theme接口。需要采用时，读取其实际代码并把颜色、字体、材质与布局参数接入本片统一样式，去除示例品牌/文案/数据；其依赖与许可先核实，不盲目执行上游安装脚本，不加载其整套SKILL来替换本产线。
