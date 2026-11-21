# FredTalk 的准备与调用

## 需要另外准备

- [FredTalk 原项目](https://github.com/njrhts2kvv-star/FredTalk)。本插件只提供独立入口和衔接规则，不把上游源库、组件包、字体、音乐或Node依赖塞进下载包。
- 按上游当前说明取得所需组件源码。能看预览不等于源码已安装，也不等于取得了素材商用权；不自动下载全库或会员包。
- 一份本片独立的Remotion工程。按上游模板与锁文件准备Node依赖、可用浏览器、FFmpeg/FFprobe。不要把本插件用于源码检查的node_modules当作FredTalk渲染环境。
- 你有权处理的定稿、声音、图片、证据和品牌资料。

本次横屏样片使用FredTalk commit `59b9e9957957dc9f3fd94ab78f95cec33c29e915` 与Remotion `4.0.515`。这是已试的组合，不是对任意新版本或所有系统的兼容保证。源库升级先检查变化，不批量升级其他产线。

## 给插件准确路径

以下命令从**当前安装插件的根目录**运行，尖括号替换为自己电脑的真实目录：

```text
python scripts/fredtalk_bridge.py status --root "<FredTalk源库>" --renderer "<本片Remotion工程>"
```

也可配置 `FREDTALK_ROOT` 和 `FREDTALK_RENDERER`，再运行 `status`。路径中有空格时保留引号。环境变量只放路径，不放API密钥。

- `--root` 指向包含FredTalk的 `library/` 和 `skills/` 的仓库根。
- `--renderer` 指向包含本片 `node_modules/` 的独立渲染工程，不指向源码仓库或插件本身。
- `--project` 可额外核对本片已有风格锁，不创建目录或修改锁。

输出 `ready_for_planning` 只表示源码与本片选择允许进入规划；还要看 `renderEnvironment`。渲染依赖未配置、缺失、或只有依赖文件，分别如实显示。浏览器、FFmpeg和实际成片仍须真实运行验证。

## Windows 的一个已知前置

上游曾把作者机器上的 `apps/library/node_modules` 符号链接存入Git。Windows克隆后它可能是普通文本文件，不是安装好的依赖。先检查文件类型；不要直接对该占位运行安装，更不要递归删除不明链接。确需适配时，备份准确占位，在独立目录按锁文件安装，再按上游检查器的真实需要连接依赖。此插件只报告状态，不自动处理该链接。

## 正式开片

可以直接对助手说：

> 这条用FredTalk原生讲解风格。我提供定稿和本人录音。先核环境，再给我每段的镜头规划和关键帧，确认后制作。不要改我原来的项目或其他风格。

没选风格时，先让助手列选项；已有风格锁则继续原片。换机器时重新核路径和依赖，不复制他人的密钥或工作区。
