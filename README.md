# 泰山派 AI Box：AHT30 + ST7789

基于 [JasonYANG170/ai-box](https://gitee.com/JasonYANG170/ai-box)，本次检查的上游提交为
`ae631bef31e6e27ccddc0ac1d23fe29fcb25c2aa`。原源码使用的是 AHT10/AHTx0 和
SSD1306 I²C OLED；本版本改为 AHT30 和 SPI3 CS0 的 240×320 ST7789。

代码目录为宿主机 `/home/gzh/ai-box`，与 SDK `/home/gzh/taishanpai` 分开。
本次软件改动未重新打包固件，也未自动复制到开发板或写入原先的 `update.img`。

## 接线与固件

屏幕使用此前选定的**方案 B（spidev）**。需要启动对应的内核和设备树，
SPI3 CS0 应绑定 `spidev`，DC/RST/BL 应可由用户态申请。

| ST7789 信号 | 40 针物理脚 | SoC 引脚 | bank 内 offset |
| --- | --- | --- | --- |
| SCK / SCL | 23 | GPIO4_C2 | 18 |
| MOSI / SDA | 19 | GPIO4_C3 | 19 |
| CS | 24 | GPIO4_C6，硬件 CS0 | 22 |
| DC | 21 | GPIO4_C5 | 21 |
| RST | 7 | GPIO1_A4 | 4 |
| BL | 12 | GPIO3_C4 | 20 |
| GND | 例如 20 | GND | — |
| VCC | 按屏幕模块规格接电源 | — | — |

这里屏幕的 SDA 是 SPI MOSI，不是 I²C SDA；不接 MISO。
BL 默认高电平点亮，只用于模块允许的背光控制输入，电气要求以模块规格为准。
GPIO3_C4 的 PWM14 必须保持禁用。

AHT30 按确认的接法沿用 **I2C2 M0**：

| AHT30 信号 | RK3566 引脚 |
| --- | --- |
| SCL | GPIO0_B5 / I2C2_SCL_M0 |
| SDA | GPIO0_B6 / I2C2_SDA_M0 |
| GND | 与开发板共地 |
| VCC | 按传感器模块规格供电，I²C 上拉电平须与开发板兼容 |

默认设备 `/dev/i2c-2`、7 位地址 `0x38`。当前 SDK 已启用 I2C2 和
`CONFIG_I2C_CHARDEV=y`；若实际系统重新分配总线号，可配置设备路径。
驱动按 [奥松 AHT30 官方说明书](https://www.aosong.com/userfiles/files/media/AHT30%E6%B8%A9%E6%B9%BF%E5%BA%A6%E4%BC%A0%E6%84%9F%E5%99%A8%E8%AF%B4%E6%98%8E%E4%B9%A6%20A2-1012.pdf)
发送 `AC 33 00`，等待转换，读取 7 字节并检查 CRC、忙状态和校准状态。
温度与湿度来自同一次测量，两秒内复用有效样本。

保留原项目的 LED `GPIO0_B7` 和左/中/右键 `GPIO3_A1/A2/A3`，按键仍按高电平有效。
程序不配置按键上下拉，沿用原有接线及外部电阻。

SPI 设备号按设备树中的 `spi@fe640000` 自动查找；GPIO 全局号按 bank 标签和
实际 base 计算。物理脚号、bank offset、Linux 全局 GPIO 号不能混用。

## 先测试两种硬件

将本目录的 Python 源文件复制到开发板同一目录，以有设备访问权限的用户执行
（当前 Buildroot 可使用 root）。先运行：

```sh
python3 AHT30_test.py
```

每两秒打印一次温度和湿度，按 Ctrl+C 结束。这个测试只用 Python 标准库，
不需要 Pillow、字体、语音模型或 AI 服务。

再单独运行：

```sh
python3 -c 'import spidev'
python3 screen_test.py
```

屏幕应依次显示红、绿、蓝、白，每种两秒；结束时关闭背光并释放 GPIO。
这个测试只需要 Python 和 `spidev`，不需要 Pillow。屏幕初始化参数沿用本地
SDK 的 ST7789 驱动，默认 240×320、0°、RGB、无偏移、10 MHz。
仍须实测模块的颜色顺序、反色、方向、偏移、初始化时序和 BL 极性。

正常退出会释放 GPIO。若提示 `GPIO already exported`，先确认该引脚的使用者；
进程被强制终止可能留下 sysfs export，程序不会接管已经导出的引脚。
硬件测试和完整程序应依次运行，避免同时占用屏幕。

## 完整程序的依赖

`ALL_V2.py` 是菜单、LED、温湿度、语音 AI 的主入口；`ai.py` 是独立语音 AI 入口。
菜单、温湿度、回复和表情均改为按 ST7789 实际分辨率绘制，文本按像素宽度换行。
天气页按中键进入/退出，传感器采样不再阻塞按键线程。

Python 依赖列在 `requirements.txt`：Pillow（含 FreeType）、spidev、Vosk、
Ollama Python 客户端、PyAudio。另外需要 PortAudio、可用录音/播放设备、
`espeak-ng` 中文语音、中文 TTF/TTC 字体、Vosk 中文模型，以及运行中的 Ollama
服务和原项目使用的 `qwen2:0.5b` 模型。Ollama Python 客户端本身不包含模型或服务，
服务要求参见 [Ollama Python 官方说明](https://github.com/ollama/ollama-python#prerequisites)。

**当前已打包的 Buildroot 只有 Python 3.8.6 和 spidev，本次没有补装完整 AI 环境。**
未安装 Pillow、Vosk、Ollama 客户端、PyAudio、中文字体和上述模型等资源；
pip 与 Python SSL 也未启用。SDK 自带的 Pillow 包为 4.2.1，不能满足此版本 UI
使用的 `textbbox` API（要求 Pillow ≥8.4），仅勾选原包还不够。
因此当前固件应先执行上面的独立硬件测试，补齐依赖后再启动完整程序。

对于已经具备 pip、SSL、开发依赖的 Python 环境，可以用：

```sh
python3 -m pip install -r requirements.txt
```

这条命令不是当前 Buildroot 上的直接安装步骤。Buildroot 的这些依赖需要另行
准备对应包或 AArch64 离线安装文件；不能把宿主机 x86 的二进制扩展复制过去。

依赖、字体和模型准备好后，按实际路径设置：

```sh
export AI_BOX_FONT=/实际路径/中文字体.ttc
export VOSK_MODEL_PATH=/实际路径/vosk-model-small-cn-0.22
python3 ALL_V2.py
```

## 可调参数

| 环境变量 | 默认值 | 用途 |
| --- | --- | --- |
| `AI_BOX_I2C_DEVICE` | `/dev/i2c-2` | AHT30 所在总线 |
| `AI_BOX_SPI_DEVICE` | 自动查找 SPI3 CS0 | 必要时指定实际 `/dev/spidevB.0` |
| `AI_BOX_SPI_HZ` | `10000000` | SPI 时钟，先用 10 MHz |
| `AI_BOX_ROTATION` | `0` | `0/90/180/270`，横屏时自动交换宽高 |
| `AI_BOX_BGR` | `0` | 红蓝颠倒时试 `1` |
| `AI_BOX_INVERT` | `0` | 模块需要反色显示时试 `1` |
| `AI_BOX_X_OFFSET` / `AI_BOX_Y_OFFSET` | `0` | 地址窗口偏移，按实际模块确定 |
| `AI_BOX_BL_ACTIVE_LOW` | `0` | 低电平点亮的 BL 设为 `1` |
| `AI_BOX_FONT` | `/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc` | 中文字体文件 |
| `AI_BOX_FONT_SIZE` | `24` | 字号 |
| `VOSK_MODEL_PATH` | `/home/lckfb/vosk-model-small-cn-0.22` | 中文识别模型目录 |

例如：`AI_BOX_BGR=1 AI_BOX_ROTATION=90 python3 screen_test.py`。
驱动使用 SDK 中 spidev 3.2 已支持的 `writebytes`，每次写入不超过 4096 字节及
内核实际的 spidev 缓冲区大小；完整帧加锁，防止菜单、文本和动画交错发送。
修改后的入口不依赖 Blinka/libgpiod，仓库原有的这些库文件保留不动。

## 已执行的验证

- SDK 自带的主机端 Python 3.8.6 对修改后的文件进行语法编译，通过。
- 14 项硬件模拟测试通过：AHT30 CRC/超时/状态/温湿度配对，动态 GPIO 和 SPI
  定位，RGB565 字节顺序、分块传输、资源释放、旋转、UI 和流式回复显示。
- `git diff --check` 通过。
- 没有在开发板实测，没有确认屏幕点亮；完整语音、模型和音频链路尚未验证。

在开发机安装 Pillow 并准备 DejaVuSans.ttf 后运行：

```sh
python3 -m unittest discover -s tests -v
```

测试字体可通过 `AI_BOX_TEST_FONT=/实际路径/字体.ttf` 指定。
测试使用模拟 I²C/SPI/GPIO，不会访问真实硬件，也不要求安装 AI 库。
