# -*- coding: utf-8 -*-
"""
摸鱼小说阅读器 —— 平台无关核心
===============================
编码识别、章节解析、配置与进度读写、分页切片、字体回退。

这里不含任何 Windows / macOS 专有调用，Windows 版与 macOS 版共用同一份逻辑。
"""
import json
import os
import re
import subprocess
import sys

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

APP_DIR = os.path.dirname(os.path.abspath(__file__))
BOOKS_DIR = os.path.join(APP_DIR, "books")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
PROGRESS_PATH = os.path.join(APP_DIR, "progress.json")

# 各平台默认中文字体
DEFAULT_FONT = "Microsoft YaHei UI" if IS_WIN else "PingFang SC"

DEFAULT_CONFIG = {
    "font_family": DEFAULT_FONT,
    "font_size": 16,
    "text_color": "#ffffff",
    "letter_spacing": 2,
    "line_spacing": 12,
    "words_per_page": 80,
    "auto_hide_delay": 2,
    "win_width": 800,
    "win_height": 60,
    "text_offset_x": 8,
    "text_offset_y": 4,
}

# 全局热键定义：(动作名, 显示用键名, Windows 虚拟键码, pynput 键名)
# pynput 是 macOS 版用的全局热键库（基于 Quartz 事件监听）
HOTKEYS = [
    ("prev", "Alt+Z", 0x5A, "<alt>+z"),
    ("next", "Alt+C", 0x43, "<alt>+c"),
    ("boss", "Alt+V", 0x56, "<alt>+v"),
    ("books", "Alt+B", 0x42, "<alt>+b"),
    ("chapters", "Alt+G", 0x47, "<alt>+g"),
    ("settings", "Alt+S", 0x53, "<alt>+s"),
    ("move", "Alt+D", 0x44, "<alt>+d"),
]

# 设置面板里的候选字体
FONT_CHOICES_WIN = [
    "微软雅黑", "微软雅黑 UI", "黑体", "宋体", "楷体", "仿宋",
    "华文行楷", "华文楷体", "华文隶书", "华文新魏", "方正舒体", "幼圆",
    "Consolas", "Courier New",
]
FONT_CHOICES_MAC = [
    "PingFang SC", "苹方-简", "苹方-特", "Songti SC", "STSong",
    "Heiti SC", "STHeiti", "Kaiti SC", "Yuanti SC", "Lantinghei SC",
    "Hiragino Sans GB", "Helvetica Neue", "Menlo", "Monaco",
]


# ---------------- 编码 ----------------
def detect_encoding(raw: bytes):
    if raw[:3] == b"\xef\xbb\xbf":
        return "utf-8-sig"
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return "utf-16"
    # 优先按 UTF-8 解码并统计坏字节比例：<0.1% 视为 UTF-8，否则回退 GB18030
    try:
        text = raw.decode("utf-8", errors="replace")
        bad_ratio = text.count("\ufffd") / max(len(text), 1)
        if bad_ratio < 0.001:
            return "utf-8"
    except Exception:
        pass
    try:
        raw.decode("gb18030")
        return "gb18030"
    except UnicodeDecodeError:
        return "utf-8"


# ---------------- 章节 ----------------
CN_NUM = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
          "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "百": 100, "千": 1000}


def cn_to_int(s: str) -> int:
    """中文数字转整数：一→1 十一→11 二十三→23 一百零五→105"""
    total, num = 0, 0
    for ch in s:
        v = CN_NUM.get(ch, 0)
        if v >= 10:
            total += num * v if num > 0 else v
            num = 0
        else:
            num = v
    return total + num


def chapter_no(num_str: str):
    """章节数字统一转 int，阿拉伯和中文数字归一化"""
    if num_str.isdigit():
        return int(num_str)
    return cn_to_int(num_str)


def parse_chapters(text: str):
    """返回 [(标题, 起始字符偏移), ...]；合并同一章的相邻重复（目录行+正文标题）"""
    pattern = re.compile(
        r"^\s*第\s*([0-9]+|[一二三四五六七八九十百千零两]+)\s*([章回节卷集部])([^\n]{0,40})?\s*$",
        re.MULTILINE)
    chapters = []
    prev_no = None
    for m in pattern.finditer(text):
        no = chapter_no(m.group(1))
        if no == prev_no:
            continue  # 与上一章同号：视为目录/正文重复，跳过
        prev_no = no
        kind = m.group(2)
        title = (m.group(3) or "").strip()
        chapters.append((f"第{no}{kind} {title}".strip(), m.start()))
    return chapters


# ---------------- 配置 / 进度 ----------------
def load_config(path: str = CONFIG_PATH):
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_config(cfg, path: str = CONFIG_PATH):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_progress(path: str = PROGRESS_PATH):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_progress(prog, path: str = PROGRESS_PATH):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(prog, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ---------------- 字体 ----------------
def font_choices():
    """返回本平台可用的候选中文字体名列表。"""
    base = FONT_CHOICES_MAC if IS_MAC else FONT_CHOICES_WIN
    try:
        import tkinter.font as tkfont
        avail = set(tkfont.families())
    except Exception:
        return list(base)
    picked = [f for f in base if f in avail]
    if not picked:
        picked = [f for f in base if f in avail] or list(base)
    return picked


def resolve_font(family: str, fallback: str = DEFAULT_FONT) -> str:
    """配置里的字体本机没有时回退到平台默认字体。

    例：Windows 上存了 '微软雅黑'，拷到 Mac 上没这个字体，就换成苹方。
    """
    try:
        import tkinter.font as tkfont
        avail = set(tkfont.families())
    except Exception:
        return family
    if not family or family in avail:
        return family or fallback
    if fallback in avail:
        return fallback
    return family


# ---------------- 杂项 ----------------
def open_folder(path: str):
    """用系统默认程序打开目录。"""
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    if IS_WIN:
        os.startfile(path)
    elif IS_MAC:
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def page_slice(text: str, start: int, step: int):
    """返回 (本页文字, 进度百分比)。"""
    seg = text[start:start + step]
    pct = int(start * 100 / max(1, len(text)))
    return seg, pct
