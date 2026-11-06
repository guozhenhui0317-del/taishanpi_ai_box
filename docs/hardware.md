# 硬件接线与自检

## 固件要求

屏幕使用**方案 B（spidev）**。开发板需要启动对应的内核和设备树：SPI3 CS0 绑定
`spidev`，DC/RST/BL 可由用户态申请，GPIO3_C4 的 PWM14 保持禁用。
本仓库的软件整理没有重新打包 SDK 固件，也没有把程序写入之前生成的 `update.img`。

SPI 设备号按设备树中的 `spi@fe640000` 自动查找；GPIO 全局号按 bank 标签和实际
base 计算。物理脚号、bank 内 offset 和 Linux 全局 GPIO 号不能混用。

## ST7789

| 屏幕信号 | 40 针物理脚 | SoC 引脚 | bank 内 offset |
| --- | --- | --- | --- |
| SCK / SCL | 23 | GPIO4_C2 | 18 |
| MOSI / SDA | 19 | GPIO4_C3 | 19 |
| CS | 24 | GPIO4_C6，硬件 CS0 | 22 |
| DC | 21 | GPIO4_C5 | 21 |
| RST | 7 | GPIO1_A4 | 4 |
| BL | 12 | GPIO3_C4 | 20 |
| GND | 例如 20 | GND | — |
| VCC | 按屏幕模块规格接电源 | — | — |

屏幕的 SDA 是 SPI MOSI，不是 I²C SDA；不接 MISO。BL 默认高电平点亮，仅用于模块
允许的背光控制输入，电气要求以模块规格为准。

在仓库根目录运行：

```sh
python3 -c 'import spidev'
python3 -m ai_box screen
```

屏幕应依次显示红、绿、蓝、白，每种两秒；结束时关闭背光并释放 GPIO。这个测试只需要
Python 和 `spidev`，不需要 Pillow、字体或 AI 依赖。

初始化参数沿用 SDK 的 ST7789 驱动，默认 240×320、0°、RGB、无偏移、10 MHz。
模块的颜色顺序、反色、方向、偏移、初始化时序和 BL 极性仍须上板确认。例如红蓝颠倒或
需要横屏时，可以分别调整对应参数：

```sh
AI_BOX_BGR=1 python3 -m ai_box screen
AI_BOX_ROTATION=90 python3 -m ai_box screen
```

驱动使用 spidev 3.2 已支持的 `writebytes`，每次写入不超过 4096 字节及内核实际的
spidev 缓冲区大小；完整帧加锁，避免多个绘制线程交错传输。

## AHT30

沿用已确认的 **I2C2 M0**：

| 传感器信号 | RK3566 引脚 |
| --- | --- |
| SCL | GPIO0_B5 / I2C2_SCL_M0 |
| SDA | GPIO0_B6 / I2C2_SDA_M0 |
| GND | 与开发板共地 |
| VCC | 按传感器模块规格供电，I²C 上拉电平须与开发板兼容 |

默认设备 `/dev/i2c-2`、7 位地址 `0x38`。当前 SDK 已启用 I2C2 和
`CONFIG_I2C_CHARDEV=y`；若实际系统重新分配总线号，可配置设备路径。

```sh
python3 -m ai_box sensor
```

每两秒打印一次温度和湿度，按 Ctrl+C 退出。只使用 Python 标准库。

驱动按[奥松 AHT30 官方说明书](https://www.aosong.com/userfiles/files/media/AHT30%E6%B8%A9%E6%B9%BF%E5%BA%A6%E4%BC%A0%E6%84%9F%E5%99%A8%E8%AF%B4%E6%98%8E%E4%B9%A6%20A2-1012.pdf)
发送 `AC 33 00`，等待转换，读取 7 字节并检查 CRC、忙状态和校准状态。
温度与湿度来自同一次测量，两秒内复用有效样本。

## LED 与按键

保留原项目接线：LED 为 `GPIO0_B7`，左、中、右键依次为 `GPIO3_A1/A2/A3`。
按键仍按高电平有效，程序不配置上下拉，沿用原有接线及外部电阻。

```sh
python3 -m ai_box led
```

LED 亮五秒、灭五秒循环；Ctrl+C 退出时置低并释放 GPIO。
菜单中使用左右键选择功能，中键进入或退出温湿度页。传感器采样不会阻塞按键线程。

## 硬件参数

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

正常退出会释放 GPIO。若提示 `GPIO already exported`，先确认该引脚的使用者；
进程被强制终止可能留下 sysfs export，程序不会接管已经导出的引脚。
硬件测试和完整程序应依次运行，避免同时占用屏幕。
