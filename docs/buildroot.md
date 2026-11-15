# 运行环境

目前使用适配官方 3.1 寸 MIPI 触摸屏的 Debian 图形环境。触摸菜单需要 Tk、Pillow（8.4 或更新版本）和中文字体。

本地“AI助手”需要 PyAudio、PortAudio、麦克风、扬声器、Vosk 中文识别模型、Ollama 客户端及服务、
大语言模型和 Piper 语音合成组件。大模型、Vosk 和 Piper 模型放在挂载到 `/mnt/modelsd` 的 SD 卡上；
模型和 Ollama 服务需要另外配置。未挂载 SD 卡或缺少大模型、Vosk 模型时，进入本地助手会提示；
Piper 模型缺失会在语音播报时报告。菜单在进入语音助手时才加载相应依赖，Python 依赖见
[requirements.txt](../requirements.txt)。

原 Buildroot 固件缺少图形菜单及完整语音环境，不能直接运行当前完整程序。硬件连接和屏幕操作见
[硬件说明](hardware.md)。

小智联网模式需要 PyAudio、音频设备、`websockets`、系统 `libopus` 和网络，不加载 SD 卡模型。
天气页面需要网络访问 Open-Meteo 或 wttr.in；网络已连接时，单个天气服务仍可能超时。
