# -*- coding: utf-8 -*-
"""
摸鱼小说阅读器 MoYu Reader
================================
一个轻量、透明的悬浮小说阅读器（Windows）。

特点：
- 透明悬浮：文字浮在桌面上，背景完全透明且点击穿透
- 全局置顶：永远在其他窗口之上
- 全局快捷键：翻页 / 老板键 / 章节 / 书架 / 设置
- 鼠标移开自动隐藏：离开阅读区超过设定秒数自动隐藏，移回自动显示
- 老板键：一键隐藏 / 显示
- 章节解析：自动识别"第X章"并支持跳转
- 阅读进度自动保存
- 大文件无压力：仅在打开时解码一次，翻页是纯内存切片

用法：
    pythonw moyu_reader.py

快捷键（默认）：
    Alt+Z  上一页
    Alt+C  下一页
    Alt+V  老板键（显示/隐藏）
    Alt+B  书架
    Alt+G  章节跳转
    Alt+S  设置

书本目录：与脚本同目录的 books/ 文件夹，放入 .txt 即可。
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import shutil
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog
import tkinter.font as tkfont

# ---------------- Windows API ----------------
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
WM_HOTKEY = 0x0312
VK_Z, VK_C, VK_V = 0x5A, 0x43, 0x56
VK_B, VK_S, VK_G = 0x42, 0x53, 0x47
VK_D = 0x44

# 托盘相关常量
WM_USER = 0x0400
WM_TRAYICON = WM_USER + 20
WM_RBUTTONUP = 0x0205
WM_LBUTTONUP = 0x0202
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x1, 0x2, 0x4
IDI_APPLICATION = 32512


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("hWnd", wt.HWND),
        ("uID", wt.UINT),
        ("uFlags", wt.UINT),
        ("uCallbackMessage", wt.UINT),
        ("hIcon", wt.HICON),
        ("szTip", ctypes.c_wchar * 128),
        ("dwState", wt.DWORD),
        ("dwStateMask", wt.DWORD),
        ("szInfo", ctypes.c_wchar * 256),
        ("uTimeout", wt.UINT),
        ("szInfoTitle", ctypes.c_wchar * 179),
        ("dwInfoFlags", wt.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wt.HICON),
    ]


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.UINT),
        ("style", wt.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE),
        ("hIcon", wt.HICON),
        ("hCursor", wt.HANDLE),
        ("hbrBackground", wt.HBRUSH),
        ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
        ("hIconSm", wt.HICON),
    ]


user32.LoadIconW.restype = wt.HICON
# 注意：LoadIconW 第二参可以是整数资源 ID（IDI_APPLICATION），不能声明为 LPCWSTR
user32.CreateWindowExW.restype = wt.HWND
user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.RegisterClassExW.argtypes = [ctypes.c_void_p]
user32.CreatePopupMenu.restype = wt.HMENU
user32.DestroyMenu.argtypes = [wt.HMENU]
user32.AppendMenuW.restype = ctypes.c_int
user32.AppendMenuW.argtypes = [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
user32.TrackPopupMenu.restype = ctypes.c_int
user32.TrackPopupMenu.argtypes = [wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, wt.HWND, ctypes.c_void_p]
user32.GetCursorPos.argtypes = [ctypes.c_void_p]
user32.SetForegroundWindow.argtypes = [wt.HWND]
kernel32.GetModuleHandleW.restype = wt.HMODULE
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

APP_DIR = os.path.dirname(os.path.abspath(__file__))
BOOKS_DIR = os.path.join(APP_DIR, "books")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
PROGRESS_PATH = os.path.join(APP_DIR, "progress.json")

MAGIC_BG = "#010203"   # 透明魔术色：此颜色的像素完全透明且点击穿透

DEFAULT_CONFIG = {
    "font_family": "Microsoft YaHei UI",
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


class MoYuReader:
    def __init__(self, root):
        self.root = root
        self.root.withdraw()  # 主窗口隐藏，只用 Toplevel 阅读窗

        self.config = self._load_config()
        self.progress = self._load_progress()

        self.book_name = None
        self.book_text = ""
        self.book_encoding = "utf-8"
        self.book_total = 0
        self.start = 0
        self.chapters = []
        self._running = True
        self._away_time = 0.0
        self._show_time = 0.0  # 窗口显示时刻，用于宽限期
        self._last_activity = time.time()  # 最近一次阅读活动（翻页等）
        self.indicator = None  # 自动隐藏后留下的指示小点
        self.move_mode = False  # 位置调整模式（Alt+D 切换）
        self._tray_hwnd = None
        self._nid = None
        self._tray_menu = None
        self._tray_wndproc_ref = None
        self._menu_close_time = 0.0  # 托盘菜单关闭时刻，用于防误触

        self._build_reader_window()
        self._build_panels()
        self._start_threads()

        # 自动打开上次阅读的书
        last = self.progress.get("_last", None)
        if last and os.path.exists(os.path.join(BOOKS_DIR, last)):
            self.open_book(last)
        else:
            self.show_bookshelf()

        self.show_reader()  # 启动即显示，并开启宽限期

    # ---------- 配置/进度 ----------
    def _load_config(self):
        cfg = dict(DEFAULT_CONFIG)
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:
            pass
        return cfg

    def _save_config(self):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load_progress(self):
        try:
            with open(PROGRESS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_progress(self):
        try:
            with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
                json.dump(self.progress, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ---------- 阅读窗 ----------
    def _build_reader_window(self):
        w = tk.Toplevel(self.root)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.attributes("-transparentcolor", MAGIC_BG)
        w.configure(bg=MAGIC_BG)
        ww = self.config["win_width"]
        wh = self.config["win_height"]
        wx = self.config.get("win_x", int((w.winfo_screenwidth() - ww) / 2))
        wy = self.config.get("win_y", 60)
        w.geometry(f"{ww}x{wh}+{wx}+{wy}")
        w.attributes("-alpha", 1.0)
        self.read_win = w

        self.font_obj = tkfont.Font(
            family=self.config["font_family"],
            size=self.config["font_size"],
        )

        self.label = tk.Text(
            w, bg=MAGIC_BG, fg=self.config["text_color"],
            font=self.font_obj, wrap="char",
            bd=0, highlightthickness=0,
            spacing1=self.config["line_spacing"],
            spacing3=self.config["line_spacing"],
            state="disabled", cursor="arrow",
        )
        self._apply_text_position()

        # 工具条
        bar = tk.Frame(w, bg=MAGIC_BG)
        btns = [
            ("上一页", self.turn_page, False),
            ("下一页", self.turn_page, True),
            ("章节", self.show_chapters),
            ("书架", self.show_bookshelf),
            ("设置", self.show_settings),
            ("隐藏", self.hide_reader),
            ("退出", self.quit_app),
        ]
        for text, cmd, *args in btns:
            b = tk.Button(bar, text=text, command=(lambda c=cmd, a=args: c(*a)),
                          bg=MAGIC_BG, fg="#888888", bd=0, relief="flat",
                          activebackground=MAGIC_BG, activeforeground="#ffffff",
                          cursor="hand2", font=("Microsoft YaHei UI", 9))
            b.pack(side="left", padx=4)
        self.toolbar = bar

        # 交互
        self.label.bind("<Button-1>", self._start_drag)
        self.label.bind("<B1-Motion>", self._on_drag)
        self.label.bind("<ButtonRelease-1>", self._on_drag_end)
        self.label.bind("<Button-3>", self._toggle_toolbar)
        self.label.bind("<MouseWheel>", self._on_wheel)
        self.label.bind("<Double-Button-1>", self._on_double_click)
        self._drag_off = (0, 0)

        self._apply_style()

    def _font(self):
        return self.font_obj

    def _apply_text_position(self):
        ox = self.config.get("text_offset_x", 8)
        oy = self.config.get("text_offset_y", 4)
        ww = self.config["win_width"]
        wh = self.config["win_height"]
        self.label.place(x=ox, y=oy,
                         width=max(50, ww - ox - 8),
                         height=max(20, wh - oy - 4))

    def _apply_style(self):
        self.font_obj.configure(
            family=self.config["font_family"],
            size=self.config["font_size"],
        )
        self.label.configure(
            fg=self.config["text_color"],
            spacing1=self.config["line_spacing"],
            spacing3=self.config["line_spacing"],
        )
        self.read_win.geometry(f"{self.config['win_width']}x{self.config['win_height']}")
        self._apply_text_position()
        self._render()

    # ---------- 面板 ----------
    def _build_panels(self):
        self.bookshelf_win = None
        self.chapter_win = None
        self.settings_win = None

    def show_bookshelf(self):
        if self.bookshelf_win is not None and self.bookshelf_win.winfo_exists():
            self.bookshelf_win.lift()
            return
        win = tk.Toplevel(self.root)
        win.title("书架")
        win.geometry("360x420")
        win.attributes("-topmost", True)
        self.bookshelf_win = win

        def refresh():
            for row in tree.get_children():
                tree.delete(row)
            if not os.path.isdir(BOOKS_DIR):
                os.makedirs(BOOKS_DIR)
            for fn in sorted(os.listdir(BOOKS_DIR)):
                if fn.lower().endswith(".txt"):
                    prog = self.progress.get(fn, {})
                    pct = prog.get("pct", 0)
                    mark = "当前" if fn == self.book_name else ""
                    tree.insert("", "end", values=(fn, f"{pct}%", mark))

        tree = ttk.Treeview(win, columns=("name", "pct", "cur"), show="headings",
                            height=16)
        tree.heading("name", text="书名")
        tree.heading("pct", text="进度")
        tree.heading("cur", text="")
        tree.column("name", width=190)
        tree.column("pct", width=60)
        tree.column("cur", width=50)
        tree.pack(fill="both", expand=True, padx=8, pady=8)

        def open_selected(_=None):
            sel = tree.selection()
            if sel:
                self.open_book(tree.item(sel[0], "values")[0])

        tree.bind("<Double-Button-1>", open_selected)

        def import_book():
            path = filedialog.askopenfilename(
                title="选择小说", filetypes=[("文本", "*.txt"), ("所有", "*.*")])
            if not path:
                return
            os.makedirs(BOOKS_DIR, exist_ok=True)
            dst = os.path.join(BOOKS_DIR, os.path.basename(path))
            shutil.copy2(path, dst)
            refresh()
            self.open_book(os.path.basename(path))

        btns = tk.Frame(win)
        tk.Button(btns, text="导入书籍", command=import_book).pack(side="left", padx=4)
        tk.Button(btns, text="打开目录", command=self._open_books_dir).pack(side="left", padx=4)
        tk.Button(btns, text="刷新", command=refresh).pack(side="left", padx=4)
        btns.pack(pady=6)
        refresh()

    def _open_books_dir(self):
        os.makedirs(BOOKS_DIR, exist_ok=True)
        os.startfile(BOOKS_DIR)

    def show_chapters(self):
        if self.book_name is None or not self.chapters:
            return
        if self.chapter_win is not None and self.chapter_win.winfo_exists():
            self.chapter_win.lift()
            return
        win = tk.Toplevel(self.root)
        win.title(f"章节 - {self.book_name}")
        win.geometry("320x420")
        win.attributes("-topmost", True)
        self.chapter_win = win

        lb = tk.Listbox(win, font=("Microsoft YaHei UI", 10))
        lb.pack(fill="both", expand=True, padx=6, pady=6)
        current = 0
        for i, (title, off) in enumerate(self.chapters):
            lb.insert("end", title)
            if off <= self.start:
                current = i
        if self.chapters:
            lb.selection_set(current)
            lb.see(current)

        def jump(_=None):
            sel = lb.curselection()
            if sel and self.chapters:
                _, off = self.chapters[sel[0]]
                self.start = off
                self._save_progress()
                self._render()

        lb.bind("<Double-Button-1>", jump)
        lb.bind("<Return>", jump)

    def show_settings(self):
        if self.settings_win is not None and self.settings_win.winfo_exists():
            self.settings_win.lift()
            return
        win = tk.Toplevel(self.root)
        win.title("设置")
        win.geometry("360x360")
        win.attributes("-topmost", True)
        self.settings_win = win
        c = self.config

        def set_key(key, var, apply=False):
            def cb(val=None):
                self.config[key] = var.get()
                self._save_config()
                if apply:
                    self._apply_style()
            return cb

        pad = {"padx": 10, "pady": 4}

        # 字体选择
        tk.Label(win, text="字体：", font=("Microsoft YaHei UI", 10)).pack(anchor="w", **pad)
        font_var = tk.StringVar(value=c["font_family"])
        fonts = ["微软雅黑", "微软雅黑 UI", "黑体", "宋体", "楷体", "仿宋",
                 "华文行楷", "华文楷体", "华文隶书", "华文新魏", "方正舒体", "幼圆",
                 "Consolas", "Courier New"]
        avail = set(tkfont.families())
        fonts = [f for f in fonts if f in avail or f == "微软雅黑 UI"]
        cb = ttk.Combobox(win, textvariable=font_var, values=fonts, state="readonly")
        cb.pack(fill="x", **pad)
        cb.bind("<<ComboboxSelected>>", lambda e: (
            self.config.__setitem__("font_family", font_var.get()),
            self._save_config(),
            self._apply_style(),
        ))

        var_fs = tk.IntVar(value=c["font_size"])
        tk.Scale(win, from_=10, to=40, orient="horizontal", label="字号",
                 variable=var_fs, command=set_key("font_size", var_fs, True)).pack(fill="x", **pad)

        var_wpp = tk.IntVar(value=c["words_per_page"])
        tk.Scale(win, from_=20, to=300, orient="horizontal", label="每页字数",
                 variable=var_wpp, command=set_key("words_per_page", var_wpp)).pack(fill="x", **pad)

        var_ad = tk.IntVar(value=c["auto_hide_delay"])
        tk.Scale(win, from_=1, to=30, orient="horizontal", label="自动隐藏秒数",
                 variable=var_ad, command=set_key("auto_hide_delay", var_ad)).pack(fill="x", **pad)

        var_wh = tk.IntVar(value=c["win_height"])
        tk.Scale(win, from_=30, to=300, orient="horizontal", label="窗口高度",
                 variable=var_wh,
                 command=set_key("win_height", var_wh, True)).pack(fill="x", **pad)

        tk.Label(win, text="文字颜色：", font=("Microsoft YaHei UI", 10)).pack(anchor="w", **pad)
        colors = ["#ffffff", "#ffff00", "#00ff00", "#ff8800", "#ff00ff", "#00ffff", "#aaaaaa"]
        frm = tk.Frame(win)
        frm.pack(**pad)

        def set_color(cl):
            self.config["text_color"] = cl
            self._save_config()
            self._apply_style()

        for cl in colors:
            tk.Button(frm, text="  ", bg=cl, width=3,
                      command=lambda c=cl: set_color(c)).pack(side="left", padx=2)

        tk.Label(win, text="快捷键：Alt+Z 上一页 | Alt+C 下一页 | Alt+V 老板键 | "
                           "Alt+B 书架 | Alt+G 章节 | Alt+S 设置 | Alt+D 位置调整",
                 font=("Microsoft YaHei UI", 9), fg="#666666",
                 justify="left", wraplength=320, anchor="w").pack(fill="x", **pad)

    # ---------- 阅读 ----------
    def open_book(self, fn):
        path = os.path.join(BOOKS_DIR, fn)
        if not os.path.exists(path):
            return
        # 后台线程读取解码，避免大文件卡住界面
        self._show_hint(f"正在打开 {fn} ...")
        threading.Thread(target=self._load_book_thread, args=(path, fn), daemon=True).start()

    def _load_book_thread(self, path, fn):
        try:
            with open(path, "rb") as f:
                raw = f.read()
            enc = detect_encoding(raw)
            text = raw.decode(enc, errors="replace")
        except Exception:
            text = raw.decode("utf-8", errors="replace")
            enc = "utf-8"
        chapters = parse_chapters(text)
        self.root.after(0, lambda: self._finish_open(fn, text, enc, chapters))

    def _finish_open(self, fn, text, enc, chapters):
        self.book_name = fn
        self.book_encoding = enc
        self.book_text = text
        self.book_total = len(text)
        self.chapters = chapters
        prog = self.progress.get(fn, {})
        self.start = prog.get("start", 0)
        self.progress["_last"] = fn
        self._save_progress()
        self._render()

    def _show_hint(self, msg):
        self.label.configure(state="normal")
        self.label.delete("1.0", "end")
        self.label.insert("end", msg)
        self.label.configure(state="disabled")

    def turn_page(self, nxt):
        if self.book_name is None:
            return
        self._last_activity = time.time()  # 翻页刷新计时
        step = self.config["words_per_page"]
        self.start = max(0, min(self.start + (step if nxt else -step), max(0, self.book_total - 1)))
        self._save_progress()
        self._render()

    def _render(self):
        c = self.config
        self.label.configure(state="normal")
        self.label.delete("1.0", "end")
        if self.book_name is None:
            self.label.insert("end", "无书可读\n按 Alt+B 打开书架")
        else:
            seg = self.book_text[self.start:self.start + c["words_per_page"]]
            pct = int(self.start * 100 / max(1, self.book_total))
            self.label.insert("end", f"{seg}\n\n[{self.book_name}] {pct}%")
            self.progress.setdefault(self.book_name, {})["start"] = self.start
            self.progress[self.book_name]["pct"] = pct
            self.progress[self.book_name]["total"] = self.book_total
        self.label.configure(state="disabled")

    # ---------- 显示/隐藏 ----------
    def show_reader(self):
        self._away_time = 0.0
        self._show_time = time.time()
        self._last_activity = time.time()
        self._hide_indicator()
        self.read_win.deiconify()
        self.read_win.lift()
        self.read_win.attributes("-topmost", True)

    def hide_reader(self, by_auto=False):
        self.read_win.withdraw()
        self._away_time = 0.0
        if by_auto:
            self._show_indicator()

    def _show_indicator(self):
        """自动隐藏后，在窗口位置留一个小色点，鼠标移上去即可恢复"""
        if self.indicator is not None and self.indicator.winfo_exists():
            self.indicator.deiconify()
            self.indicator.lift()
            return
        dot = tk.Toplevel(self.root)
        dot.overrideredirect(True)
        dot.attributes("-topmost", True)
        dot.configure(bg=self.config["text_color"])
        x = self.read_win.winfo_x() + self.read_win.winfo_width() // 2
        y = self.read_win.winfo_y() + self.read_win.winfo_height() // 2
        dot.geometry(f"10x10+{x - 5}+{y - 5}")
        dot.bind("<Enter>", lambda e: self.show_reader())
        self.indicator = dot

    def _hide_indicator(self):
        if self.indicator is not None and self.indicator.winfo_exists():
            self.indicator.withdraw()

    def toggle_boss(self):
        if self.read_win.winfo_viewable():
            self.hide_reader()
        else:
            self.show_reader()

    def _toggle_toolbar(self, _=None):
        if self.toolbar.winfo_manager():
            self.toolbar.pack_forget()
        else:
            self.toolbar.pack(side="bottom", fill="x")

    # ---------- 拖拽 ----------
    def _start_drag(self, e):
        self._last_activity = time.time()
        self._drag_off = (e.x_root - self.read_win.winfo_x(),
                          e.y_root - self.read_win.winfo_y())

    def _on_drag(self, e):
        SNAP = 30  # 边缘吸附阈值(px)
        x = e.x_root - self._drag_off[0]
        y = e.y_root - self._drag_off[1]
        w = self.read_win.winfo_width()
        h = self.read_win.winfo_height()
        # 使用工作区（避开任务栏）
        wa_w = user32.GetSystemMetrics(61)   # SM_CXWORKAREA
        wa_h = user32.GetSystemMetrics(62)   # SM_CYWORKAREA
        if abs(x) < SNAP:
            x = 0
        elif abs(wa_w - (x + w)) < SNAP:
            x = wa_w - w
        if abs(y) < SNAP:
            y = 0
        elif abs(wa_h - (y + h)) < SNAP:
            y = wa_h - h
        self.read_win.geometry(f"+{x}+{y}")

    def _on_drag_end(self, _=None):
        self.config["win_x"] = self.read_win.winfo_x()
        self.config["win_y"] = self.read_win.winfo_y()
        self._save_config()

    def _on_wheel(self, e):
        if not self.move_mode:
            self._last_activity = time.time()
            self.turn_page(e.delta < 0)

    def _on_double_click(self, _=None):
        if self.move_mode:
            return
        self._last_activity = time.time()
        if self.book_name is None:
            self.show_bookshelf()
        else:
            self.turn_page(True)

    def toggle_move_mode(self):
        """Alt+D：进入/退出位置调整模式，退出时保存窗口位置"""
        self.move_mode = not self.move_mode
        if self.move_mode:
            self.show_reader()
            self._away_time = 0.0
            self._show_time = time.time()
            self.label.configure(state="normal")
            self.label.delete("1.0", "end")
            self.label.insert("end",
                              "【位置调整模式】\n按住文字拖动到想要的位置，再按 Alt+D 结束并保存")
            self.label.configure(state="disabled")
        else:
            self.config["win_x"] = self.read_win.winfo_x()
            self.config["win_y"] = self.read_win.winfo_y()
            self._save_config()
            self._render()

    # ---------- 线程 ----------
    def _start_threads(self):
        threading.Thread(target=self._hotkey_loop, daemon=True).start()
        # 自动隐藏用主线程轮询（tkinter 非线程安全）
        self._auto_hide_tick()

    def _any_panel_open(self):
        for w in (self.bookshelf_win, self.chapter_win, self.settings_win):
            if w is not None and w.winfo_exists() and w.winfo_viewable():
                return True
        return False

    def _auto_hide_tick(self):
        if not self._running:
            return
        try:
            if self.read_win.winfo_viewable():
                # 面板打开时不自动隐藏；显示后 3 秒宽限期内也不隐藏（防瞬隐）
                if self._any_panel_open() or time.time() - self._show_time < 3:
                    self._away_time = 0.0
                else:
                    pt = POINT()
                    user32.GetCursorPos(ctypes.byref(pt))
                    rx = self.read_win.winfo_x()
                    ry = self.read_win.winfo_y()
                    rw = self.read_win.winfo_width()
                    rh = self.read_win.winfo_height()
                    inside = rx <= pt.x <= rx + rw and ry <= pt.y <= ry + rh
                    if inside:
                        # 光标在文字上：永不隐藏
                        self._away_time = 0.0
                    elif time.time() - self._last_activity < self.config["auto_hide_delay"]:
                        # 刚翻过页（在设定的隐藏时间内）：暂不隐藏，重新计时
                        self._away_time = 0.0
                    else:
                        self._away_time += 0.5
                        if self._away_time >= self.config["auto_hide_delay"]:
                            self.hide_reader(by_auto=True)
            else:
                self._away_time = 0.0
        except Exception:
            pass
        self.root.after(500, self._auto_hide_tick)

    def _hotkey_loop(self):
        try:
            self._create_tray_window()  # 托盘窗口挂在热键线程，消息循环一起处理
        except Exception as e:
            self._log_err(f"tray create failed: {e!r}")
        user32.RegisterHotKey(None, 1, MOD_ALT, VK_Z)   # 上一页
        user32.RegisterHotKey(None, 2, MOD_ALT, VK_C)   # 下一页
        user32.RegisterHotKey(None, 3, MOD_ALT, VK_V)   # 老板键
        user32.RegisterHotKey(None, 4, MOD_ALT, VK_B)   # 书架
        user32.RegisterHotKey(None, 5, MOD_ALT, VK_G)   # 章节
        user32.RegisterHotKey(None, 6, MOD_ALT, VK_S)   # 设置
        user32.RegisterHotKey(None, 7, MOD_ALT, VK_D)   # 位置调整模式
        msg = wt.MSG()
        while self._running:
            if user32.GetMessageW(ctypes.byref(msg), None, 0, 0) <= 0:
                break
            if msg.message == WM_HOTKEY:
                self._on_hotkey(msg.wParam)
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _on_hotkey(self, hk_id):
        actions = {
            1: lambda: self.turn_page(False),
            2: lambda: self.turn_page(True),
            3: self.toggle_boss,
            4: self.show_bookshelf,
            5: self.show_chapters,
            6: self.show_settings,
            7: self.toggle_move_mode,
        }
        act = actions.get(hk_id)
        if act:
            self.root.after(0, act)

    def _log_err(self, msg):
        try:
            with open(os.path.join(APP_DIR, "error.log"), "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        except Exception:
            pass

    # ---------- 系统托盘 ----------
    def _create_tray_window(self):
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._tray_wndproc_ref = WNDPROC(self._tray_wndproc)
        wc.hInstance = kernel32.GetModuleHandleW(None)
        wc.lpszClassName = "MoYuTrayWnd"
        user32.RegisterClassExW(ctypes.byref(wc))
        self._tray_hwnd = user32.CreateWindowExW(
            0, "MoYuTrayWnd", "", 0, 0, 0, 0, 0,
            None, None, wc.hInstance, None)
        self._add_tray_icon()

    def _add_tray_icon(self):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._tray_hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAYICON
        nid.hIcon = user32.LoadIconW(None, IDI_APPLICATION)
        nid.szTip = "摸鱼阅读器"
        self._nid = nid
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))

    def _remove_tray_icon(self):
        if self._nid is not None:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
            self._nid = None

    def _tray_wndproc(self, hwnd, msg, wp, lp):
        if msg == WM_TRAYICON:
            action = lp & 0xFFFF
            if action == WM_RBUTTONUP:
                # 直接在本线程（热键线程）同步弹菜单，避免与 Tk 主循环冲突
                pt = POINT()
                user32.GetCursorPos(ctypes.byref(pt))
                try:
                    self._show_tray_menu(pt.x, pt.y)
                except Exception as e:
                    self._log_err(f"tray menu failed: {e!r}")
            elif action == WM_LBUTTONUP:
                # 防误触：菜单刚关闭时，忽略松键（防止选中菜单项后残留的左键松开触发切换）
                if time.time() - self._menu_close_time < 0.4:
                    self._log_err(f"WM_LBUTTONUP ignored (menu just closed, "
                                  f"dt={time.time()-self._menu_close_time:.2f}s)")
                    return user32.DefWindowProcW(hwnd, msg, wp, lp)
                self._log_err("WM_LBUTTONUP -> toggle_boss")
                self.root.after(0, self.toggle_boss)
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    def _show_tray_menu(self, x, y):
        """Win32 原生弹出菜单：定位准确、点击外部自动关闭、同步阻塞"""
        MF_STRING, MF_SEPARATOR = 0x0, 0x800
        TPM_RIGHTBUTTON, TPM_RETURNCMD = 0x2, 0x0100
        items = [
            (1, "显示/隐藏阅读窗", self.toggle_boss),
            (2, "书架", self.show_bookshelf),
            (3, "设置", self.show_settings),
            (None, None, None),          # 分隔线
            (4, "退出", self.quit_app),
        ]
        hmenu = user32.CreatePopupMenu()
        for i, label, _ in items:
            if label is None:
                user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
            else:
                user32.AppendMenuW(hmenu, MF_STRING, i, label)
        # 同步阻塞直到菜单关闭；返回选中的命令 id（0=未选择/被点击外部关闭）
        # 先设为前台窗口，否则后台线程弹的菜单无法正常激活（点击外部不会关闭）
        user32.SetForegroundWindow(self._tray_hwnd)
        cmd = user32.TrackPopupMenu(hmenu, TPM_RIGHTBUTTON | TPM_RETURNCMD,
                                    x, y, 0, self._tray_hwnd, None)
        user32.DestroyMenu(hmenu)
        self._menu_close_time = time.time()  # 记录关闭时刻，防误触
        self._log_err(f"menu closed, cmd={cmd}")
        dispatched = False
        for i, _, fn in items:
            if i is not None and cmd == i:
                self._log_err(f"dispatch item {i}: {getattr(fn, '__name__', fn)}")
                dispatched = True
                try:
                    self.root.after(0, fn)
                except Exception as e:
                    self._log_err(f"dispatch failed: {e!r}")
        if not dispatched:
            self._log_err("no item matched (cmd=0 or unknown)")

    def quit_app(self):
        self._running = False
        self._remove_tray_icon()
        for i in range(1, 8):
            try:
                user32.UnregisterHotKey(None, i)
            except Exception:
                pass
        self.root.destroy()


def main():
    os.makedirs(BOOKS_DIR, exist_ok=True)
    root = tk.Tk()
    app = MoYuReader(root)
    root.mainloop()


if __name__ == "__main__":
    main()
