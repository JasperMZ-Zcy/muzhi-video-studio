# 本人录音：先试听确认，再锁真实SRT

适用于尚未锁声轨的新正式片。制作入口接收内容入口的确认稿与牧之本人录音；先核旧项目锁与本次授权。原始文件和哈希永久保留，处理只写新副本和裁剪映射，不覆盖原件，也不因工具报成功就说已经听过或确认。

## 克制处理与试听

先对照确认稿听原音，标出明确的重录、口误、过长空白和仍需人工判断的差异。只在能确定不会改变意思与语气的范围清理副本，保留正常停顿、呼吸、强调和自然节奏；不变速、不改音色、不用TTS补词，不为了凑稿把临场新表达当口误删除。若录音与稿有实质不同且不能判明，指出句子、所在时间和可能影响，请牧之决定保留录音表达、重录或改稿。

先用实际工具的 `--help` 核命令和输出。原件若是M4A，先用 `scripts/narration_track.py decode-local --project <项目> --source <项目内原M4A> --source-sha256 <原件SHA> --wav-output <项目内新PCM WAV>` 调使用者已有的本机FFmpeg解码为标准PCM16 WAV；原M4A不动，WAV必须是新路径，并保存同名 `.decode-receipt.json`。编辑计划除 `original_wav/original_sha256` 指向该WAV外，还须写 `source_recording/source_recording_sha256` 与 `decode_receipt/decode_receipt_sha256`，把原录音、解码副本和回执连成同一来源。已有合格PCM WAV则直接保原件，不造M4A解码回执。没有FFmpeg就保持原件并报告缺口，插件不替用户安装。

`scripts/narration_track.py prepare --project <项目> --edit-plan artifacts/narration-edit-plan.json --candidate audio/final-candidate.wav` 只做PCM WAV副本的精确样本裁剪，输出候选、映射、哈希与 `.receipt.json`。编辑计划的 `cuts[]` 仅能列已审的 `clear_retake`、`clear_mistake`、`overlong_silence` 区间，记录原WAV/确认稿哈希；不能确定的口语差异留在 `unresolved_spoken_differences`，先由人判断。脚本不会识别口误，也不会作听感判断。把候选音轨、与原声的差异及需要决定的句子交牧之试听；收到真实试听确认后，用 `confirm-audio --project <项目> --receipt <候选WAV.receipt.json> --user-quote <牧之对该版最终音轨的实际确认原话>` 绑定该候选和回执。未确认或候选已变就停在候选，不能转写、锁SRT或进入正式导演。已锁旧声轨继续原合同，不用新版默认重剪。

## 转写、校对与锁定

牧之只需试听候选并确认最终音轨；SRT逐字与时码校对由制作助手负责，不要求牧之逐句签字幕。只对已经 `confirm-audio` 绑定的最终音轨转写/对齐。可选本机转写要求使用者自行准备兼容的 `faster-whisper` Python包和**已存在的本地模型snapshot目录**，本片显式指定目录；插件不自带模型，不自动下载。用 `narration_track.py asr-status --project <项目> --model-dir <既存snapshot绝对目录>` 核依赖和模型文件；`ready` 只表示文件/包齐备，不证明模型可加载、转写完成或正式质量。就绪且本片授权时，用 `transcribe-local --project <项目> --candidate <已确认候选WAV> --out-dir <项目内新目录> --model-dir <同一快照>` 在CPU上离线生成草稿JSON、音轨SHA和回执；它会核同版试听确认，输出目录须新。缺依赖、模型或可用算力就走人工校对路径，不下载/静默降级或转收费云端。

ASR只提供草稿，制作助手仍须按最终音轨逐句听音、校对字词、否定、数字、归属、语气词、实际临场表达与时码，并与确认稿比较。SRT时码必须落在最终音轨实际语音位置，不能把原稿、旧录音或自动转写文本直接冒充准确字幕。字幕文本与本人口播存在需牧之决定的实质表达差异时，指出具体句子和影响，再处理内容决定；一般转写/时码校对由制作助手完成。

先运行 `narration_track.py compare --receipt <候选WAV.receipt.json> --srt <校对SRT>`，检查具体差异、时长、尾部对齐提醒与 `difference_digest`。这个摘要只锁定稿、音轨和SRT的差异身份，不证明字幕字词或时码准确；制作助手须听音完成校对并留下实际记录。之后用 `lock-srt --receipt <同一回执> --srt <同一SRT> --difference-digest <本次精确值> --audio-quote <先前confirm-audio的同一牧之确认原话> --srt-quote <制作助手实际逐字及时码校对记录>` 保存 `artifacts/narration-lock.json`；新编的另一句批准话不能替代原确认。`--srt-quote` 是制作端的校对依据，不得伪写为牧之逐句批准；两个quote都不能预填。脚本检查文件身份与时域，不能证明ASR字词正确或替牧之试听。正式 `studio` 导演核同版原稿、最终音轨、SRT、计划与锁回执；任一文件变化即重核受影响字幕和镜头，不能用旧锁放行新版。单轨无BGM导出工具只适用于它自身声明的无裁音、无混音条件，处理后音轨和配乐片不得套用该出口。
