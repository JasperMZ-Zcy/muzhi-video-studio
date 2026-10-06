# 逐镜同版导演审核

确认稿、牧之试听确认的最终音轨及制作助手校对的真实SRT齐备后，沿唯一`motion_plan`分段；`artifacts/director-storyboard.json`按同一segment ID引用计划，不另建镜头路线表。项目原`design.md`、已确认画风、用户批准、37项质量门和费用边界仍各自有效。无声`authored_screen_timing`只是研究，不能冒正式口播。

给用户的HTML由`scripts/resource_handoff.py board --project <项目> --plan <计划相对路径> --contract artifacts/director-storyboard.json --output <项目内新版.html>`生成。每镜并排核原话与真实cue、观众误解和本镜目标、所选机制/来源、可识别对象、进入→接触或变化→结果→停读→退出、主焦点和旧焦点退场、实际近成片关键帧、下一镜接力及可修改处。真实本人声的每镜播放器从最终母轨按SRT cue时段定位，静读资料镜也可单独听本镜原声；HTML结构不能证明用户实际听过。需要连续动作、自然接触或节奏才能判断的镜头，附本片同版真实短预演；只有首帧、提示词、灰卡或旧项目图不能证明这段运动。纯官方原件停读若完整读点已清楚，可写`static_reading_reason`并用一张真实帧；原页缩图不能冒完整条件与否定已读。

合同须同时有`preproduction_contract_version:1`与`director_review_contract_version:1`，绑定当前计划、设计、原稿、SRT、最终音轨、可视HTML及每镜真实关键帧的路径/SHA。`preview_binding.keyframes`与`shots[].keyframes`逐镜对应同一文件；`preproduction_check(require_board=True)`会重生HTML核其SHA，任意另存的合法HTML也不能冒同版。外部封存且精确验证过的旧same-script v2项目才依原身份有限读回；只有旧标签、HANDOFF、design或一个旧插件锁的新绑v2仍走当前同版门。`director_review_gate.py validate --stage plan`只表示可交用户审阅，`batch`另核当前整版的真实批准摘要，`master`另核真实成片和完整终检；脚本通过不证明镜头语义或审美正确。

用户可以逐镜指出问题，制作端仅返工受影响段和相邻接力；每次修改更新原计划/实际帧/HTML/摘要后，再请用户确认**当前完整版本**，不要求逐帧弹窗批准。独立审者先读原稿、看片前后状态及必要短预演，复述自己认出的人/物、关系变化和判断，再与原意核对；静态哈希、字段pass和作者解释不能代替这次观察。批量制作、图生提交或收费步骤还要分别过本片渠道、音乐方法、预算和原生产门。成片后按同一镜头次序看正常速度声画、字幕、手机阅读、连续动作与前后衔接，不能把片前静帧批准当成成片批准。
