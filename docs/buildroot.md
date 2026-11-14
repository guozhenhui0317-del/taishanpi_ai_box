# 运行环境

目前使用适配官方 3.1 寸 MIPI 触摸屏的 Debian 图形环境。触摸菜单需要 Tk、Pillow（8.4 或更新版本）和中文字体。

语音助手还需要 PyAudio、PortAudio、录音和播放设备、Vosk 中文识别模型、Ollama 客户端及服务、
可用的大语言模型和语音播报组件。Python 依赖见 [requirements.txt](../requirements.txt)；模型和
Ollama 服务需要另外配置。两个模型均从挂载在 `/mnt/modelsd` 的 SD 卡读取，卡未挂载或文件缺失时
菜单会显示提示。菜单在进入语音助手时才加载语音依赖。

原 Buildroot 固件缺少图形菜单及完整语音环境，不能直接运行当前完整程序。硬件连接和屏幕操作见
[硬件说明](hardware.md)。

小智联网模式还需要 `websockets`、系统 `libopus` 和网络；无需加载 SD 卡模型。
