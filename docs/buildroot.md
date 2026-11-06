# Buildroot 运行环境

## 当前固件能运行什么

此前打包的固件包含 **Python 3.8.6 和 spidev 3.2**。本次软件目录整理没有重新编译或
打包固件，也没有自动复制程序到开发板。

| 命令 | 运行依赖 | 当前固件情况 |
| --- | --- | --- |
| `python3 -m ai_box --help` | Python 标准库 | 已具备 |
| `python3 -m ai_box sensor` | Python 标准库、I2C2 设备 | 软件依赖已具备，需实测接线 |
| `python3 -m ai_box led` | Python 标准库、GPIO sysfs | 软件依赖已具备，需实测接线 |
| `python3 -m ai_box screen` | Python、spidev、方案 B 设备树 | 软件依赖已具备，需实测屏幕 |
| `python3 -m ai_box run` | 上述硬件、Pillow、中文字体 | 尚缺 Pillow 和字体 |
| `python3 -m ai_box voice` | 屏幕显示依赖、完整语音 AI 环境 | 尚未配齐 |

菜单中的 LED 和温湿度功能不依赖语音库。选择 AI 功能时才加载语音依赖。

## 菜单与显示依赖

需要 **Pillow ≥8.4（含 FreeType 支持）** 和中文 TTF/TTC 字体。SDK 自带 Pillow 包为
4.2.1，不支持本程序使用的 `textbbox` API，仅勾选原包还不够。

```sh
export AI_BOX_FONT=/实际路径/中文字体.ttc
python3 -m ai_box run
```

| 环境变量 | 默认值 | 用途 |
| --- | --- | --- |
| `AI_BOX_FONT` | `/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc` | 中文字体文件 |
| `AI_BOX_FONT_SIZE` | `24` | 菜单与文本字号 |

文本按像素宽度换行，菜单、温湿度、回复和表情按屏幕实际分辨率绘制。
屏幕旋转、颜色和偏移参数见[硬件说明](hardware.md)。

## 语音 AI 依赖

完整 Python 依赖列在根目录的 [requirements.txt](../requirements.txt)：
Pillow、spidev、Vosk、Ollama Python 客户端和 PyAudio。此外还需要：

- PortAudio，以及可用的录音和播放设备。
- `espeak-ng` 及中文语音数据。
- Vosk 中文识别模型。
- 运行中的 Ollama 服务，以及原项目使用的 `qwen2:0.5b` 模型。

Ollama Python 客户端不包含模型或服务，参见
[Ollama Python 官方说明](https://github.com/ollama/ollama-python#prerequisites)。

准备好这些依赖后运行：

```sh
export AI_BOX_FONT=/实际路径/中文字体.ttc
export VOSK_MODEL_PATH=/实际路径/vosk-model-small-cn-0.22
python3 -m ai_box voice
```

`VOSK_MODEL_PATH` 默认是 `/home/lckfb/vosk-model-small-cn-0.22`。
也可以运行 `python3 -m ai_box run`，从菜单进入 AI 功能。

## 安装方式的限制

当前固件未安装 Pillow、Vosk、Ollama 客户端、PyAudio、中文字体或上述模型，
**pip 和 Python SSL 也未启用**。以下命令仅适用于已经具备 pip、SSL 和开发依赖的
Python 环境，并非当前 Buildroot 的直接安装步骤：

```sh
python3 -m pip install -r requirements.txt
```

Buildroot 需要准备对应的软件包或与目标 Python、AArch64 和运行库兼容的离线安装文件。
Pillow 等二进制扩展不能从 x86 宿主机直接复制到开发板。

当前验证覆盖语法和模拟硬件行为。尚未确认开发板上的屏幕点亮、完整语音识别、模型服务
和音频链路；应先完成[独立硬件自检](hardware.md)，再逐步验证显示菜单与语音功能。
