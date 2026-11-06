# -*- coding: utf-8 -*-

import asyncio
from contextlib import ExitStack
import json
import os
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import ollama
import pyaudio
import vosk

from aht30 import AHT30
from display_ui import face_frame, load_font, menu_frame, text_frame
from linux_gpio import GPIO
from st7789 import ST7789

stop_event = threading.Event()

# 菜单配置 ================================================
MENU_LEVEL_MAIN = 0
MENU_LEVEL_SUB = 1  # (新增) 二级菜单层级
menu_config = {
    MENU_LEVEL_MAIN: ["手电筒", "AI助手", "天气"],
    MENU_LEVEL_SUB: ["开启", "关闭", "返回"]  # (新增) 二级菜单项
}
# 共享状态管理 ============================================
lock = threading.Lock()
# 定义标签
shared_data = {
    "menu_level": MENU_LEVEL_MAIN, #菜单内容 
    "main_index": 0, # 主菜单位置
    "sub_index": 0,  # (新增) 二级菜单索引
    "display_dirty": True, #显示历史
    "ai_running": False,
    "temp_running": False,
    "exit_ai": False,
    "force_redraw": False  # 新增强制刷新标志
}

def update_shared_state(key, value):
    """读取标签状态"""
    with lock:
        shared_data[key] = value

def get_shared_state(key):
    """获取标签"""
    with lock:
        return shared_data[key]

def get_all_shared_state():
    """读取全部标签状态"""
    with lock:
        return shared_data.copy()

# 显示系统 ================================================
def render_display(state):
    """@brief Render the selected menu at the display's native resolution."""
    if state["display_dirty"] or state["force_redraw"]:
        level = state["menu_level"]
        index = state["main_index"] if level == MENU_LEVEL_MAIN else state["sub_index"]
        display.display(menu_frame(display.width, display.height, menu_config[level], index, font))
        update_shared_state("force_redraw", False)

# 按键处理线程 ============================================
debounce_time = 0.05
last_left = False
last_center = False
last_right = False
last_action_time = 0

# 修改按键检测线程
def button_thread():
    """优化后的按键线程"""
    global last_left, last_center, last_right, last_action_time
    
    while not stop_event.is_set():
        current_time = time.time()
        
        # 新增：AI运行时提高检测频率
        detection_interval = 0.01 if get_shared_state("ai_running") else 0.05
        if current_time - last_action_time >= debounce_time:
            check_left()
            check_right()
            check_center()
        
        time.sleep(detection_interval)  # 动态调整检测间隔

def check_left():
    """左键检测"""
    global last_left, last_action_time
    current = left.value
    if current and not last_left:
        on_left_press()
        last_action_time = time.time()
    last_left = current

def check_right():
    """右键检测"""
    global last_right, last_action_time
    current = right.value
    if current and not last_right:
        on_right_press()
        last_action_time = time.time()
    last_right = current

def check_center():
    """中间键检测"""
    global last_center, last_action_time
    current = center.value
    if current and not last_center:
        on_center_press()
        last_action_time = time.time()
    last_center = current

# 按键处理 ================================================
def on_left_press():
    """修改后的左键处理"""
    current_level = get_shared_state("menu_level")
    if current_level == MENU_LEVEL_MAIN:
        new_index = max(0, get_shared_state("main_index") - 1)
        update_shared_state("main_index", new_index)
    elif current_level == MENU_LEVEL_SUB:
        new_index = max(0, get_shared_state("sub_index") - 1)
        update_shared_state("sub_index", new_index)
    update_shared_state("display_dirty", True)

def on_right_press():
    """修改后的右键处理"""
    current_level = get_shared_state("menu_level")
    if current_level == MENU_LEVEL_MAIN:
        max_index = len(menu_config[MENU_LEVEL_MAIN])-1
        new_index = min(get_shared_state("main_index") + 1, max_index)
        update_shared_state("main_index", new_index)
    elif current_level == MENU_LEVEL_SUB:
        max_index = len(menu_config[MENU_LEVEL_SUB])-1
        new_index = min(get_shared_state("sub_index") + 1, max_index)
        update_shared_state("sub_index", new_index)
    update_shared_state("display_dirty", True)

def on_center_press():
    """修改后的中间键处理"""
    current_level = get_shared_state("menu_level")
    
    if current_level == MENU_LEVEL_MAIN:
        if get_shared_state("main_index") == 0:  # 主功能2
            # 进入二级菜单
            update_shared_state("menu_level", MENU_LEVEL_SUB)
            update_shared_state("sub_index", 0)
        if get_shared_state("main_index") == 1:
            if not get_shared_state("ai_running"):
                threading.Thread(target=run_ai_task, daemon=True).start()
            else:
                update_shared_state("exit_ai", True)
                update_shared_state("force_redraw", True)
        if get_shared_state("main_index") == 2:
            update_shared_state("temp_running", not get_shared_state("temp_running"))
            update_shared_state("force_redraw", True)
    elif current_level == MENU_LEVEL_SUB:
        sub_index = get_shared_state("sub_index")
        if sub_index == 0:  # 显示hi
            led_on()
        elif sub_index == 1:  # 显示hello
            led_off()
        elif sub_index == 2:  # 返回
            update_shared_state("menu_level", MENU_LEVEL_MAIN) 
            update_shared_state("main_index", 1)  
    update_shared_state("display_dirty", True)



def run_ai_task():
    """在独立线程中运行AI任务"""
    update_shared_state("ai_running", True)
    try:
        asyncio.run(mainai())
    finally:
        update_shared_state("ai_running", False)
        update_shared_state("exit_ai", False)
        update_shared_state("force_redraw", True)

# 假设这是一个全局变量
led_state = False



def led_on():
    """优化后的LED开启函数"""
    global led_state, led
    if not led_state:
        led.value = 1
        led_state = True

def led_off():
    """修复条件的LED关闭函数"""
    global led_state, led
    if led_state:  # 修正条件判断
        led.value = 0
        led_state = False

def output_AHT30():
    """@brief Render one paired AHT30 sample without blocking the button thread."""
    try:
        temperature, humidity = sensor.read()
        show_on_display(f"温度: {temperature:.1f} C\n湿度: {humidity:.1f} %")
    except OSError as error:
        print(f"AHT30: {error}")
        show_on_display("温湿度读取失败")

# 加载语音识别模型
model_path = os.environ.get("VOSK_MODEL_PATH", "/home/lckfb/vosk-model-small-cn-0.22")

# 会话历史记录，保存用户和AI的对话
conversation_history = [
    {"role": "system", "content": "你是嘉立创EDA-小嘉，是一个运行在泰山派上的离线本地大模型语音助手。"},
]
MAX_HISTORY_LENGTH = 1  # 会话历史的最大条数

asr_running = False  # 语音识别动画状态
def show_on_display(text):
    """@brief Show wrapped text using the full ST7789 screen."""
    display.display(text_frame(display.width, display.height, text, font))


def draw_face(mouth_state=0):
    """@brief Show the original animation scaled to the screen."""
    display.display(face_frame(display.width, display.height, mouth_state))

def asr_animation():
    """语音识别时的动画显示"""
    global asr_running
    frame = 0
    while asr_running and not stop_event.is_set():
        draw_face(frame % 3)  # 切换嘴巴形态
        frame += 1
        time.sleep(0.2)  # 控制动画的速度


def recognize_speech(p):
    """使用Vosk进行语音识别"""
    global asr_running
    stream = p.open(format=pyaudio.paInt16,
                    channels=1,
                    rate=16000,
                    input=True,
                    frames_per_buffer=20480)
    stream.start_stream()  # 开始音频流
    print("正在识别语音...")

    asr_running = True  # 启动动画
    animation_thread = threading.Thread(target=asr_animation)  # 创建动画线程
    animation_thread.start()  # 启动动画线程

    try:
        while not get_shared_state("exit_ai") and not stop_event.is_set():
            data = stream.read(2048, exception_on_overflow=False)
            if get_shared_state("exit_ai") or stop_event.is_set():
                break
            data = stream.read(2048, exception_on_overflow=False)  # 读取音频数据
            if recognizer.AcceptWaveform(data):  # 如果识别到有效语音
                result = recognizer.Result()  # 获取识别结果
                result_json = json.loads(result)  # 解析JSON结果
                if "text" in result_json:
                    text = result_json['text']  # 提取识别的文本
                    print(f"识别到的文字: {text}")
                    asr_running = False  # 停止动画
                    animation_thread.join()  # 等待动画线程结束
                    draw_face(1)  # 显示微笑
                    time.sleep(1)
                    stream.stop_stream()  # 停止音频流
                    stream.close()  # 关闭音频流
                    return text  # 返回识别到的文本
    except IOError:
        pass

    asr_running = False
    animation_thread.join()  # 等待动画线程结束
    stream.stop_stream()
    stream.close()

def clean_text(text):
    """清理文本中的无效字符"""
    return re.sub(r"[^\u4e00-\u9fa5，。！？]", "", text)

async def generate_and_play_text(input_text):
    """生成AI回复并播报"""
    draw_face(1)  # 显示微笑
    time.sleep(1)

    conversation_history.append({"role": "user", "content": input_text})  # 记录用户输入
    response = ollama.chat(model="qwen2:0.5b", messages=conversation_history, stream=True)  # 获取AI回复
    generated_text = ""
    for chunk in response:
        if get_shared_state("exit_ai") or stop_event.is_set():
            break
        raw_text = chunk['message']['content'] or ""
        if raw_text:
            clean_tts_text = clean_text(raw_text)  # 清理文本
            generated_text += raw_text
            show_on_display(generated_text)  # 显示累计回复
            print(f"当前生成: {generated_text}")
            if clean_tts_text:
                subprocess.run(['espeak-ng', '-v', 'zh', clean_tts_text])  # 语音播报
    
    conversation_history.append({"role": "assistant", "content": generated_text})  # 记录AI回复
    draw_face(1)  # 显示微笑
    time.sleep(1)



def get_temperature_humidity(sensor):
    """获取温湿度数据并播报"""
    try:
        temperature, humidity = sensor.read()
        print(f"当前气温为{temperature:.2f}度")  # 打印温度
        print(f"当前湿度为百分之{humidity:.2f}")  # 打印湿度
        show_on_display(f"温度: {temperature:.2f} C\n湿度: {humidity:.2f} %")
        subprocess.run(['espeak-ng', '-v', 'zh', f'当前气温为{temperature:.2f} 摄氏度，当前湿度为百分之 {humidity:.2f} 百分比'])  # 语音播报
    except Exception as e:
        print(f"Error: {e}")

# 修改AI主函数
async def mainai():
    
    
    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=2)
    p = pyaudio.PyAudio()

    try:
        while not get_shared_state("exit_ai") and not stop_event.is_set():
            recognized_text = await loop.run_in_executor(
                executor, 
                lambda: recognize_speech(p) if not get_shared_state("exit_ai") else ""
            )
            
            if get_shared_state("exit_ai") or stop_event.is_set():
                break
            print(f"识别到的语音：{recognized_text}")
    
            if "开启" in recognized_text:
                led.value = 1  # 开灯
                subprocess.run(['espeak-ng',  '-v', 'zh', '开灯'])  # 播报开灯
                show_on_display("开启")  # 显示开灯
            elif "停止"in recognized_text:
                led.value = 0  # 关灯
                subprocess.run(['espeak-ng',  '-v', 'zh', '关灯'])  # 播报关灯
                show_on_display("关灯")  # 显示关灯
            elif "天气" in recognized_text or "温度" in recognized_text or "湿度" in recognized_text:
                get_temperature_humidity(sensor)  # 获取并播报温湿度
            else:
                await generate_and_play_text(recognized_text)  # AI生成回复并播报
        
        p.terminate()  # 释放音频资源
    finally:
        p.terminate()
        update_shared_state("menu_level", MENU_LEVEL_MAIN)
        update_shared_state("main_index", 0)  # 可选：重置菜单选项
        update_shared_state("display_dirty", True)
        update_shared_state("force_redraw", True)  # 强制刷新
        update_shared_state("ai_running", False)
        update_shared_state("exit_ai", False)
        if not stop_event.is_set():
            display.clear()

def init_hardware():
    """@brief Initialize the confirmed screen/sensor wiring and original controls."""
    global display, sensor, led, left, center, right
    display = ST7789()
    sensor = AHT30()
    led = GPIO(0, 15, initial=False)
    left = GPIO(3, 1)
    center = GPIO(3, 2)
    right = GPIO(3, 3)

# 在程序启动时初始化硬件

# 主程序 ================================================
def main():
    """@brief Run the menu and release hardware on startup failure or shutdown."""
    global font, model, recognizer
    button_thread_instance = None
    stop_event.clear()
    try:
        font = load_font()
        model = vosk.Model(model_path)
        recognizer = vosk.KaldiRecognizer(model, 16000)
        init_hardware()
        button_thread_instance = threading.Thread(target=button_thread, daemon=True)
        button_thread_instance.start()
        last_sample = float("-inf")
        while not stop_event.is_set():
            current_state = get_all_shared_state()
            dirty = current_state["display_dirty"] or current_state["force_redraw"]
            if not current_state["ai_running"]:
                if current_state["temp_running"]:
                    if dirty or time.monotonic() - last_sample >= 2:
                        output_AHT30()
                        last_sample = time.monotonic()
                        update_shared_state("display_dirty", False)
                        update_shared_state("force_redraw", False)
                elif dirty:
                    render_display(current_state)
                    update_shared_state("display_dirty", False)
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        update_shared_state("exit_ai", True)
        if button_thread_instance is not None:
            button_thread_instance.join()
        with ExitStack() as cleanup:
            for name in ("display", "sensor", "led", "left", "center", "right"):
                resource = globals().get(name)
                if resource is not None:
                    cleanup.callback(resource.close)

if __name__ == "__main__":
    main()
