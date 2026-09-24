# 项目协议与工具

入口脚本是插件根目录`scripts/project_state.py`。纯标准库，无网络、无外部费用、不自动生成媒体。它没有MCP常驻服务或拦截所有操作的系统钩子；只有实际调用并处理检查结果时才发挥作用，不能声称安装后绝对不会漂移。

## 用法

以下`<ROOT>`是插件根，`<PROJECT>`是当前用户明确放在范围内的项目。使用当前系统Python并按shell规则正确传递JSON。

```text
python <ROOT>/scripts/project_state.py status --project <PROJECT>
python <ROOT>/scripts/project_state.py init --project <PROJECT>
python <ROOT>/scripts/project_state.py lock --project <PROJECT> --key voice.main --file media/voice.wav
python <ROOT>/scripts/project_state.py approve --project <PROJECT> --key voice.main --quote "用户真实确认原话"
python <ROOT>/scripts/project_state.py verify --project <PROJECT> --key voice.main
python <ROOT>/scripts/project_state.py verify --project <PROJECT> --key cover.current --hash-only
python <ROOT>/scripts/project_state.py plan-change --domain covers
python <ROOT>/scripts/project_state.py override --project <PROJECT> --scope project --key visual.warm --value true --quote "明确调整整条片子的视觉风格，不只是封面"
python <ROOT>/scripts/project_state.py override --project <PROJECT> --scope revision --revision-id cover-v2 --key cover.visual.warm --value true --quote "只把封面改暖一些"
python <ROOT>/scripts/project_state.py set-stage --project <PROJECT> --stage scheduled --quote "已经设置定时"
python <ROOT>/scripts/project_state.py package --project <PROJECT> --manifest <明确文件清单.json> --destination <现有父目录下的交付目录>
```

文件清单格式为`{"files":["output/final.mp4","output/cover.png","output/title.txt"]}`，仅相对本项目的显式文件。路径不明、同名碰撞、现有同名文件内容不同都停止，不先复制半套。当前工具不删除文件，也不自动替换旧桌面版本；用户要求原地替换时，先核精确目标与可回退源，再在该明确授权下单独替换。

## 状态与审批

- `init`是幂等的新状态初始化，不导入旧项目阶段。已有项目先读`status`返回的旧记录；如需启用插件状态，根据实际项目阶段显式`set-stage`并回填当前摘要，不能把旧片重置为待开工。
- `planning/assets/editing/review/delivered/scheduled/published`只表示当前工作位置，不是质量审查自动通过。
- 锁定使用文件内容SHA。批准绑定该内容哈希和真实原话，不是文件名；同文件改内容后旧批准失效。
- “执行授权”“内部质检”“用户实际视觉认可”不是同一件事。只有最后一种用`approve`；前两种在本项目已有修改/QA记录保留真实原话、范围与证据，哈希一致性单独用`verify --hash-only`，不得为了默认verify通关而补造用户批准。
- 普通状态操作使用`--expected-revision`可防止并发人员覆盖新状态。锁超时先查另一位是否仍在操作，不把强删锁当常规动作。
- `published`必须同时给真实`--platform`、`--post-id`、带时区的`--published-at`与`--quote`。工具只校验输入格式，不代替实际平台证据。它当前记录单次发布信息，不是完整多平台数据库；多个平台完整原生记录仍放现有工作台/项目发布清单，不能误称一条发布覆盖全部平台。
- `scheduled`也只是状态索引。定时的平台、时区、预计时间、排期编号、采用封面哈希和平台替换回执仍必须写进现有项目发布清单/工作台；插件不会推断这些字段。重复scheduled调用不生成新发布证明。封面只在本地更新时，平台替换状态保留not_attempted；不得擅自修改已定时帖。
- `override`只能写创意、样式等项目要求，禁止把认证、资金、发布权限塞进覆盖字段。一次覆盖不修改其他项目，也不会更新插件全局默认。
- 插件版本是项目创建时固定值，重复初始化不会升级；升级插件后新项目用新版本，旧项目改版本必须做具体迁移并保留回退，不暗中更新。

## 真正减少返工

`plan-change`返回最小候选影响集合，需要结合真实引用依赖再决定实际动作。例如封面文案只影响封面与发布包；如果某条字幕同时出现在视频中，用户说只改封面就不得顺手更改视频字幕。

使用已有供应商、音频处理和视频渲染入口；本脚本不替代这些工具的实际校验。失败即报告真实缺口，不填空审批、虚构完整观看或把未发生的步骤补写成已完成。
