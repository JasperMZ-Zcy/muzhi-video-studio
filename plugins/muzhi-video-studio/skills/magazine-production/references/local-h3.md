# 本地 H3 V2 图生视频适配

本页只规定 `local-h3` 供应商的运行边界。它调用牧之远见现有的 PowerShell V2 产线，不是 MiniMax 云端 API；`minimax` 云渠道的任务、费用与回执不得混用。本插件不附带模型、ComfyUI 或许可证。

## 何时可用

- 本项目 `provider_router status` 的有效选择必须是 `local-h3`，只作用于尚未提交的镜头；已提交的 WAN、Flow、云 MiniMax 镜头继续按原任务恢复。
- 首帧和动作提示词必须是项目内已有、当前获准使用的文件。运行者从真实用户原话取得本次授权，核对设计锁和首帧批准状态；适配器的 `--authorization-quote` 只是留痕，不会验证原话真伪。输入 SHA 一变化，旧批准不能自动继承。
- 同时最多一个本地重任务。先确认没有视频渲染、批量生图或另一条 H3；不为提速跳过正式脚本的模型身份、完整预热、D 盘热槽、RAM/虚拟内存/GPU 温度及超时保护。
- 正式入口仅有 `Fast720Seven`、`Quality720Seven`、`NativeLong`。前两者输出 720×1280、24 fps、168 帧、严格七秒，来自原生 124 帧母片经运动补偿光流延展；`NativeLong` 输出 720×1280、158 帧、约 6.583 秒。均无原声。640×1152 七秒 Sage/禁 pinned 仍是单镜隔离实验，尚未升为正式 Profile；不得在此适配器启用实验开关或把实验样片说成全镜头验证。

## 两步调用

运行者先用 `provider_router.py` 登记本项目 `local-h3` 选择，再执行只读预检。若项目位于名为 `OpenMontage` 的工作区内，适配器沿项目父目录找到该工作区，并只读发现其 `services/muzhi-h3-local/scripts/generate-h3-i2v-v2.ps1`；找不到时用 `--runner` 指向真实 V2 入口，或通过持久环境变量 `MUZHI_H3_V2_RUNNER` 提供。AI 根目录及热模型目录由原 runner 解析，必要时用 `--ai-root`、`--hot-root` 明确指定，插件不把本机 G 盘写成通用默认。

```text
python <ROOT>/scripts/local_h3_adapter.py plan --project <PROJECT> --shot-id s01 --input-image assets/s01-first.png --prompt-file prompts/s01-motion.txt --profile Fast720Seven --seed 26092401 --runner <V2_RUNNER>
```

`plan` 会校验项目文件、输入哈希、生产档位，并调用正式脚本的 `-ValidateOnly`；同时只读报告本项目是否选中 `local-h3`。不启动生成、不生成镜头、不声称视觉验收。正式运行还须提交当前首帧与动作提示词的实际 SHA、真实授权原话和明确时间线位置。`--ffprobe` 指向本机可信 ffprobe；`timeline-start` 与 `usable-duration` 必须来自本条已确定的镜头安排，不能用示例数字填充正式项目。

```text
python <ROOT>/scripts/local_h3_adapter.py run --project <PROJECT> --shot-id s01 --input-image assets/s01-first.png --prompt-file prompts/s01-motion.txt --profile Fast720Seven --seed 26092401 --runner <V2_RUNNER> --ffprobe <FFPROBE> --approved-input-sha256 <CURRENT_FIRST_FRAME_SHA256> --approved-prompt-sha256 <CURRENT_PROMPT_FILE_SHA256> --authorization-quote <USER_ACTUAL_WORDS> --accept-local-heavy --timeline-start <SECONDS> --usable-duration <SECONDS>
```

运行前再次核当前项目渠道选择；确认输出名、母片、结果 JSON、项目目标与桌面副本均无碰撞。适配器在原 V2 运行目录放独占锁，避免自身并行任务；其他本机重任务仍需运行者检查。运行完成只读 `.v2-result.json`，核 `status`、输入与 Profile、原件 SHA、实际 ffprobe 宽高/帧率/帧数/时长/无音轨，再独占复制到项目 `artifacts/local-h3/media`，写逐镜 `artifacts/local-h3/deliveries/*.json`。清单字段可交 `provider_router validate-delivery --ffprobe` 复验。原运行结果 JSON、母片、`runKey`、ComfyUI 阶段日志和项目原素材均保留。

适配器成功状态仅为 `ingested_pending_visual_review`。仍要由 03 看完整动态动作、衔接、画风和口播节奏，06 做独立视觉验收，07 核技术及可回退性；项目内复制件、哈希、静帧或 `exit 0` 都不能冒称牧之已接受。失败或超时返回 `resume_required`：先看既有 attempt、V2 的各阶段 `result.json`/`metrics.csv`/ComfyUI 错误日志及现有 conditioning、latent、逐帧和 MP4。相同输入重复调用不会盲重跑；已有逐帧时只恢复封装，已有 MP4 时只核验并补交付。锁文件异常残留时由 07 确认原进程确已停止后再处理，不自动强行清除。

## 发布许可单独过闸

本地推理没有云平台单次积分费，不等于无条件商用。MiniMax H3 官方 [Community License](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/LICENSE) 排除美国、欧盟、英国、韩国等地域；达到其年度商业收入门槛需事先书面授权，公开传播机器生成内容有明确披露要求。Turbo LoRA 的独立许可也须按实际版本核对，不能覆盖 H3 基座限制。07 在正式接入及每次公开发布前核实际运行/使用与传播地域、收入条件、模型和 LoRA 版本及披露方式；06/07 未双签不进入发布。
