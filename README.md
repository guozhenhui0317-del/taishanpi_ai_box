# 泰山派 AI Box

基于立创泰山派 RK3566，使用官方 3.1 寸 MIPI 触摸屏与语音 AI。
硬件接线见[硬件说明](docs/hardware.md)，源码结构和函数讲解见[代码学习指南](docs/代码学习指南.md)。

## 使用

在适配的 Debian 图形桌面中运行：

```sh
python3 -m ai_box run       # 触摸菜单；mipi 是同义命令
python3 -m ai_box voice     # 启动后直接进入语音助手
python3 -m ai_box --help
```

主界面显示应用图标，点击“AI助手”“天气”“小智联网”“网络设置”或“旋转屏幕”即可打开对应功能。
天气和语音界面点击屏幕返回主界面，网络设置使用页面上的“返回”按钮。每次点击“旋转屏幕”图标
旋转 90°，依次循环四个方向；触摸方向同步变化，方向会在重启后保留。此设置只影响 AI Box 界面，
不改变桌面方向。

“天气”页面显示成都的网络天气。语音询问“今天天气怎么样”
或“明天天气怎么样”会直接查询成都天气。天气数据
来自 [Open-Meteo](https://open-meteo.com/)，联网失败时会显示提示。

选择“网络设置”可扫描并连接附近的 2.4 GHz Wi-Fi 或手机热点。点击网络后，使用屏幕键盘输入
密码并点击“连接”；已保存的网络可直接选择。键盘上的“大小写”和“符号”用于切换输入，密码
由系统网络管理器保存。支持开放网络和 WPA/WPA2 个人网络，切换网络后开发板 IP 可能发生变化。

菜单需要 Pillow、中文字体和图形桌面；语音助手还需要模型、音频设备和服务，详见
[运行环境说明](docs/buildroot.md)。选择语音 AI 时才加载语音依赖。

主菜单中的“AI助手”使用 SD 卡上的本地模型；“小智联网”连接小智官方服务，
首次使用时请在 [小智控制台](https://xiaozhi.me/) 添加设备并输入屏幕显示的激活码。
联网模式点击图标后开始对话，点击屏幕退出；录音会发送给官方服务处理，
该模式不需要 SD 卡。语音唤醒、设备控制和回声消除尚未实现。

## 查看调试信息

开发板开机自动启动 AI Box 后，在终端实时查看本次运行的日志：

```sh
sudo tail -F /run/ai-box/ai-box.log
```

日志包括识别出的语音文字、模型回复、处理耗时和错误。按 Ctrl+C 停止查看，不会关闭 AI Box。
日志保存在内存文件系统中，重启后清除；从终端手动启动程序时，日志直接输出到该终端。

如果尚未连接喇叭，可以在 `/etc/default/ai-box` 中设置 `AI_BOX_SPEECH=0`，跳过语音播报并尽快
恢复收音。接入喇叭后把该值改为 `1`，再重启 AI Box 即可启用播报。

在 `/etc/default/ai-box` 中设置 `AI_BOX_LLM_MODEL=deepseek-r1:1.5b` 并重启 AI Box，
即可试用 SD 卡上的 DeepSeek；设置为 `qwen2:0.5b` 可切回原模型。DeepSeek 使用 4 个 CPU
线程推理，屏幕实时显示“正在思考”，随后显示正式回答；语音只播报正式回答，最近两轮
对话也只保存正式回答。显示思考内容可以看到生成进度，最终回答仍可能需要较长时间。

正式回答会按标点分段播报。离线中文播报使用 Piper，语音模型及配置位于
`/mnt/modelsd/piper-voices/`，运行程序及兼容库位于 `/opt/ai-box/tts-runtime/`；
SD 卡未挂载或语音模型缺失时会报错。每段播报需要重新加载语音模型，段与段之间可能有延迟。

## 项目结构

```text
ai_box/              # 菜单、MIPI 触摸和语音助手
ai_box/hardware/     # Linux GPIO 驱动
docs/                # 硬件接线和运行环境
tests/               # 不访问实际硬件的自动化测试
requirements.txt     # Python 依赖
```

## 开发验证

安装 Pillow 和 DejaVuSans 字体后运行：

```sh
python3 -m unittest discover -s tests -v
```

可用 `AI_BOX_TEST_FONT=/实际路径/字体.ttf` 指定测试字体。自动测试模拟硬件，不能代替实机检查。

## 来源

基于 [JasonYANG170/ai-box](https://gitee.com/JasonYANG170/ai-box)，上游基准提交为
`ae631bef31e6e27ccddc0ac1d23fe29fcb25c2aa`。
