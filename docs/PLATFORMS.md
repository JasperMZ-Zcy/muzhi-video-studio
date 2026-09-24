# 渠道与交付合同

插件的渠道路由是**项目内记录与验证工具**，不是任何平台的 SDK、账号管理器或自动化浏览器。它不会读取凭证、执行 `tool_ref`、访问 URL、提交生成或下载文件。

## 内置渠道

| 渠道 | 模式 | 工作流输出 | 不做什么 |
| --- | --- | --- | --- |
| 本地 ComfyUI / MiniMax-H3 | `local_workflow` | 只在使用者已有模型、工作流和设备资源时登记本地镜头与回收结果 | 不附带模型，不等于云端 MiniMax，也不保证某台机器的生成时间 |
| WAN | `configured_api` | 记录本项目选择与后续回执 | 不配置凭证、不代表你提交任务或扣费 |
| MiniMax | `configured_api` | 记录本项目选择与后续回执 | 不切换模型、不购买额度、不把失败当作可重试成功 |
| Google Flow | `manual` | 按镜号交付首帧和提示词的单层手动包 | 不替你在网页或 API 中提交任务 |

WAN 和云端 MiniMax 必须由使用者先完成自己的工具连接、模型选择和授权。本地 H3 是另一条独立路线：请先核对模型与 LoRA 许可、已有工作流、显存/内存和运行时间；它不默认可用，也不会替你下载模型。Google Flow 的作用是把视觉源、动作提示和单镜信息整理成可操作的手动包；生成、下载和实际账户操作仍由使用者完成。

## 选择与切换

先查看项目当前状态：

```bash
python <PLUGIN_ROOT>/scripts/provider_router.py status --project <PROJECT_ROOT>
python <PLUGIN_ROOT>/scripts/provider_router.py list --project <PROJECT_ROOT>
```

选择只影响尚未提交的镜头，并需保留用户真实原话：

```bash
python <PLUGIN_ROOT>/scripts/provider_router.py select \
  --project <PROJECT_ROOT> --provider google-flow \
  --quote "本条未提交镜头使用 Google Flow，我手动生成"
```

已提交任务、历史回执和旧输出不会因为换渠道而被抹掉或改写。切换渠道也不等于重启内容、换画风或允许额外费用。画风另由项目风格锁管理；本地 H3、云端 MiniMax 和 Google Flow 的镜头最终仍按同一交付合同进入剪辑。

## 登记新的提供方

新提供方只登记在**当前项目**中。先决定它是已配置 API 还是手动包：

```bash
python <PLUGIN_ROOT>/scripts/provider_router.py register --help
```

`configured_api` 只接受安全的本地 capability 名称作为 `tool_ref`；它不是 URL、命令、密钥、环境变量或配置文件路径。登记成功仅表示项目可以引用该能力，`adapter_verified` 初始仍为 `false`。在真实项目中，还需由使用者验证首帧输入、模型／时长／比例、任务查询、下载、费用单位和失败恢复。

## 统一交付合同

无论镜头来自 API 还是手动生成，都需要一个项目内交付清单。核心字段包括：

- `shot_id`、`source_provider`、可选 `provider_job_id`；
- 项目内 `path` 和实际 `sha256`；
- 实测 `duration`、`width`、`height`、`fps`；
- `source_audio_removed`、`source_start`、`timeline_start`、`usable_duration`；
- 可选 `playback_rate`，只能是 `1`。

查看机器可读合同：

```bash
python <PLUGIN_ROOT>/scripts/provider_router.py contract --project <PROJECT_ROOT>
```

再用 `validate-delivery` 核文件路径、哈希和字段，用 `production_runner.py media-audit` 核实际媒体规格。不要用 JSON 中的自填时长、音轨或“已去音”布尔值代替文件探测。

## 费用仍是独立边界

选择提供方不等于允许付费。对每一个新生成请求，先由 `generation_ledger.py` 留额；未知成本继续按预估占用，失败重试需要明确的额外授权记录。详见 [快速开始](GETTING_STARTED.md#成本台账的最小示例)。
