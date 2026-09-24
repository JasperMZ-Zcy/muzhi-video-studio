# 实际执行与消耗控制

## 能做什么，依赖什么

插件给完整产线的规范、既有校验器、固定阶段入口、媒体实测、项目状态和生成台账。代理按本入口编排已有生图、ChatCut、Flow/指定供应商、音频及渲染能力，**它不是自带所有模型的一键视频应用**。没有相关供应商或渲染器时应报具体缺项，不能把校验器存在当作具备生成能力。

公开包只包含随插件发布的规则、模板与校验器。使用者应核对自己的渲染器、媒体工具与供应商连接是否可用，并在项目记录中如实写明差异；插件不自动安装依赖、不自动连接收费服务，也不假装具备未提供的工作区能力。

## 固定阶段检查

命令前缀为`python <插件根>/scripts/production_runner.py`。

| 阶段 | 命令 | 真实检查 |
| --- | --- | --- |
| 查看依赖 | `plan --stage design`（或其他阶段） | 只返回计划，不宣称通过 |
| 设计锁 | `check --project <项目> --stage design` | 原validate_design_lock，批准信息与实际图/文档SHA |
| 完整导演板 | `check --project <项目> --stage storyboard` | 原validate_director_storyboard plan |
| 批量前 | `check --project <项目> --stage batch` | 原storyboard batch与production_enforcement；缺真实样片/有声动态分镜证据拒绝 |
| 动态回收 | `check --project <项目> --stage ingest` | 原动态媒体时长校验，含探测与重复/补时检查 |
| 正式母版 | `check --project <项目> --stage master` | 原项目QA合同与生产强制合同 |
| 文件身份和媒体 | `media-audit --project <项目> --manifest <项目内媒体清单> --decode` | 实际SHA、ffprobe规格/时长/音轨、串行完整解码 |

执行`check`前，项目内`artifacts/editorial-plugin-inputs.json`声明本阶段实际输入，例如`{"files":[{"path":"design.md","sha256":"实际64位哈希","role":"design"}],"required_roles":["design"]}`。这是结构说明，哈希必须现场计算，不复制示意字符串。不符合当前合同的旧项目不能填假字段通关，也不能删掉检查项；先做有范围的合同迁移或保留真实未完成项。

视频媒体清单示例结构如下，例子中的哈希同样必须替换成真实值：

```json
{
  "max_duration_tol": 0.08,
  "files": [{
    "path": "media/01.mp4",
    "sha256": "实际SHA256",
    "kind": "video",
    "expected_duration": 6.0,
    "expected_width": 1080,
    "expected_height": 1920,
    "expected_fps": "30/1",
    "allow_audio": false
  }]
}
```

纯音频使用kind=audio、allow_audio=true及sample_rate/channels，不填假的宽高；无声视频不填假的采样率或声道数。最终带人声的成片应allow_audio=true并声明正式混音规格，不能照抄“中间素材无音轨”规则。

这些工具返回进程实际检查结果，子校验器失败即失败，即使输出文字有passed:true也不放行。不把“存在review.json”当成画面已经看过，实际视听判断和对应源文件/时码必须由代理真实完成并留记录。

## 生成前预留，生成后登记

命令前缀为`python <插件根>/scripts/generation_ledger.py`。它仅维护本项目台账，不连接供应商、不收费，也不能拦截绕过它的直接调用。

1. 将本次完整提示词、模型设置、style/design指纹、参考图或录音准备好，每个影响输出的文件都传`--input-file`。不要只传参考图而漏提示词，否则文字改了仍可能错用旧缓存。音频正式ASR按音频内容复用，局部第二路核对须单独记录用途与范围，不伪装成重跑正式全片。
2. `plan`先看费用占用；`reserve`使用用户实际授权的预算/单位，不根据口头“放开做”增加额度。正费用没有预算拒绝。普通本地无收费任务可用unit=none和estimated-cost=0。
3. 返回reuse就核旧输出后复用，返回resume先查原任务，不能再次提交；只有新reservation才允许本次供应商调用。
4. 平台返回任务ID后`attach`，成功/失败/未知后`finish`。只提交了请求不能提前写success，输出文件不存在不能登记成功。
5. 费用无回执就不传actual-cost，保持null并用估算占预算；重试需要明确retry-quote。费用台账一套单位不能混人民币/美元/平台积分，不静默换算。

```text
python <ROOT>/scripts/generation_ledger.py reserve --project <PROJECT> --kind image --key shot01 --input-file prompts/shot01.txt --input-file refs/shot01.png --input-file model-options.json --provider <实际供应商> --model <实际模型> --estimated-cost <已查估算> --budget <已批上限> --unit credits --quote "实际批准原话"
python <ROOT>/scripts/generation_ledger.py attach --project <PROJECT> --reservation-id <返回ID> --provider-job-id <供应商原任务ID>
python <ROOT>/scripts/generation_ledger.py finish --project <PROJECT> --reservation-id <返回ID> --status succeeded --output-file assets/shot01.png
```

命令工具的quote只是记录，不验证这个句子真的由用户说过；代理必须从对话/授权回执获取，不能自造。actual-cost省略是未知，不能为让预算通过乱填0。工具默认最多2个未结算任务，仍需单独遵守本机最多1个重任务，不能调大参数绕开资源纪律。

## 范围与复用

- 改封面只动covers/release，已完成镜头、音频和字幕不再生成。
- 换BGM只动对应曲与混音，旧画面bitstream保持。
- 换一个镜头只做该镜与必要衔接，不重新生成22张。
- 未改变输入且已有通过证据就复用，输入变了要重新核哈希和受影响项，不能直接沿用旧批准。
- 先做小样与低清整体检查再高清，真正节省全片错误返工；用户明确调整审核安排时仍保留真实内部质量检查。
- 一份当前状态加阶段参考，其他资料按需读取；不要反复整库扫描、开浏览器或并行多个渲染。

## 有边界的完整产线

当前工具覆盖接班/指纹/预算/阶段/媒体/平铺交付，原产线提供导演、视听、容器布局、封面和发布规则；具体镜头创作与审美仍由代理执行，供应商仍可能失败。验收应包括离线负向测试与下一条真实新片，不能声称已验证所有未来画风、音乐和账号组合永不出错。
