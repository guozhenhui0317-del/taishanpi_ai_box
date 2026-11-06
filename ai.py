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

from display_ui import face_frame, load_font, text_frame
from st7789 import ST7789

model_path = os.environ.get("VOSK_MODEL_PATH", "/home/lckfb/vosk-model-small-cn-0.22")
stop_event = threading.Event()

# 记录会话历史
conversation_history = [
    {"role": "system", "content": "你是嘉立创EDA-小嘉，是一个运行在泰山派上的离线本地大模型语音助手。"},
]
MAX_HISTORY_LENGTH = 1  # 限制会话历史的最大条数

asr_running = False  # 语音识别时的动画状态控制变量
def show_on_display(text):
    """@brief Show wrapped text using the full ST7789 screen."""
    display.display(text_frame(display.width, display.height, text, font))


def draw_face(mouth_state=0):
    """@brief Show a face animation at the screen's current resolution."""
    display.display(face_frame(display.width, display.height, mouth_state))

def asr_animation():
    global asr_running
    frame = 0
    while asr_running and not stop_event.is_set():
        draw_face(frame % 3)  # 按 0、1、2 的顺序切换嘴巴形态
        frame += 1
        time.sleep(0.2)  # 控制动画速度
def recognize_speech(p):
    """使用 Vosk 进行语音识别"""
    global asr_running
    stream = p.open(format=pyaudio.paInt16,
                    channels=1,
                    rate=16000,
                    input=True,
                    frames_per_buffer=20480)
    stream.start_stream()

    print("正在识别语音...")

    asr_running = True  # 启动动画
    animation_thread = threading.Thread(target=asr_animation)  # 创建动画线程
    animation_thread.start()

    try:
        while not stop_event.is_set():
            data = stream.read(2048, exception_on_overflow=False)  # 读取音频数据
            if recognizer.AcceptWaveform(data):  # 处理音频流
                result = recognizer.Result()  # 获取识别结果
                result_json = json.loads(result)  # 解析 JSON 数据
                if "text" in result_json:
                    text = result_json['text']  # 提取识别文本
                    print(f"识别到的文字: {text}")

                    asr_running = False  # 停止动画
                    animation_thread.join()  # 等待动画线程结束

                    draw_face(1)  # 识别完成后显示微笑表情
                    time.sleep(1)

                    # 释放音频资源
                    stream.stop_stream()
                    stream.close()
                    return text
    except IOError:
        pass

    # 释放资源
    asr_running = False
    animation_thread.join()
    stream.stop_stream()
    stream.close()
def clean_text(text):

    return re.sub(r"[^\u4e00-\u9fa5，。！？]", "", text)
async def generate_and_play_text(input_text):

    draw_face(1)  # 显示微笑表情
    time.sleep(1)

    conversation_history.append({"role": "user", "content": input_text})  # 记录用户输入
    response = ollama.chat(model="qwen2:0.5b", messages=conversation_history, stream=True)  # AI 生成回答

    generated_text = ""
    for chunk in response:
        if stop_event.is_set():
            break
        raw_text = chunk['message']['content'] or ""
        if raw_text:
            clean_tts_text = clean_text(raw_text)  # 清理文本
            generated_text += raw_text
            show_on_display(generated_text)
            print(f"当前生成: {generated_text}")
            if clean_tts_text:  # 确保有中文内容才播放
                subprocess.run(['espeak-ng', '-v', 'zh', clean_tts_text])  # 语音朗读

    conversation_history.append({"role": "assistant", "content": generated_text})  # 记录 AI 回应
    draw_face(1)  # 结束后显示微笑
    time.sleep(1)
async def main():
    """@brief Run the original voice assistant with an ST7789 display."""
    global display, font, model, recognizer
    stop_event.clear()
    font = load_font()
    model = vosk.Model(model_path)
    recognizer = vosk.KaldiRecognizer(model, 16000)
    loop = asyncio.get_event_loop()
    with ExitStack() as cleanup:
        display = ST7789()
        cleanup.callback(display.close)
        p = pyaudio.PyAudio()
        cleanup.callback(p.terminate)
        executor = ThreadPoolExecutor(max_workers=2)
        cleanup.callback(executor.shutdown, wait=True)
        try:
            while not stop_event.is_set():
                recognized_text = await loop.run_in_executor(executor, recognize_speech, p)
                if recognized_text:
                    await generate_and_play_text(recognized_text)
        finally:
            stop_event.set()

if __name__ == "__main__":
    asyncio.run(main())  # 运行主程序
