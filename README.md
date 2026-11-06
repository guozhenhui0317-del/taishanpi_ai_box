# 泰山派 AI Box

立创泰山派 RK3566 的菜单、LED、温湿度与语音 AI 程序，使用 **AHT30（I2C2）** 和
**ST7789（SPI3 CS0，240×320）**。屏幕需要方案 B（spidev）的内核和设备树。

## 项目结构

```text
ai_box/
  __main__.py       # 统一命令入口
  app.py            # 菜单、按键与功能切换
  voice.py          # 语音识别、AI 回复与播报
  ui.py             # 文本、菜单与表情绘制
  diagnostics.py    # 传感器、屏幕和 LED 自检
  hardware/         # AHT30、ST7789、Linux GPIO 驱动
docs/
  hardware.md       # 接线、固件要求和硬件参数
  buildroot.md      # 运行依赖与当前固件的限制
tests/              # 模拟硬件测试
requirements.txt    # 完整程序的 Python 依赖
```

## 运行

将仓库复制到开发板，在仓库根目录执行。先按[硬件说明](docs/hardware.md)检查接线，
再分别运行自检；每次只运行一个占用相同引脚的程序。

```sh
python3 -m ai_box --help  # 查看命令，不需要硬件或额外 Python 库
python3 -m ai_box sensor # 每两秒读取温湿度，Ctrl+C 退出
python3 -m ai_box screen # 红、绿、蓝、白各显示两秒，然后退出
python3 -m ai_box led    # 亮五秒、灭五秒循环，Ctrl+C 退出
```

`sensor` 和 `led` 只需要 Python 标准库；`screen` 还需要 `spidev`。
使用有设备访问权限的用户运行，当前 Buildroot 可使用 root。

准备好 Pillow、中文字体和 spidev 后，启动菜单：

```sh
export AI_BOX_FONT=/实际路径/中文字体.ttc
python3 -m ai_box run
```

省略 `run` 也会启动菜单。菜单中的 LED 和温湿度功能可独立使用；选择语音 AI 时才加载
语音依赖。独立语音入口为 `python3 -m ai_box voice`，所需模型、音频组件和服务见
[运行环境说明](docs/buildroot.md)。

旧入口 `ALL_V2.py`、`ai.py`、`AHT30_test.py`、`screen_test.py`、`led_test.py`
已分别统一为 `run`、`voice`、`sensor`、`screen`、`led` 子命令。

**当前已打包的 Buildroot 尚缺 Pillow、中文字体和完整语音 AI 依赖。** 可先执行硬件自检；
目录整理不会修改或重新打包固件。程序尚未完成开发板实测，屏幕参数和完整语音链路仍需验证。

## 开发验证

在开发机安装 Pillow，并准备 DejaVuSans.ttf 后运行：

```sh
python3 -m unittest discover -s tests -v
```

可用 `AI_BOX_TEST_FONT=/实际路径/字体.ttf` 指定测试字体。测试模拟 I²C、SPI 和 GPIO，
不会访问真实硬件，也不要求安装语音 AI 库。目标解释器为 Python 3.8。

## 来源

基于 [JasonYANG170/ai-box](https://gitee.com/JasonYANG170/ai-box)，上游基准提交为
`ae631bef31e6e27ccddc0ac1d23fe29fcb25c2aa`。原项目使用 AHT10/AHTx0 和 SSD1306；
本版本适配 AHT30 与 ST7789，并使用独立的 Linux GPIO 驱动。未使用的随仓库附带的
Blinka 和 platformdetect 文件已移除。
