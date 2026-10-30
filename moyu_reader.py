# -*- coding: utf-8 -*-
"""
摸鱼小说阅读器 MoYu Reader
================================
一个轻量、透明的悬浮小说阅读器（Windows / macOS 双平台）。

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
    pythonw moyu_reader.py          # Windows
    python3 moyu_reader.py          # macOS

文件划分：
    moyu_core.py        平台无关：编码识别、章节解析、配置与进度
    moyu_backend.py     平台后端入口 + Windows 实现（Win32 热键 / 托盘）
    moyu_backend_mac.py macOS 实现（pynput 热键 / NSStatusItem / 透明穿透）
    moyu_reader.py      Tk 界面（两端共用）

快捷键（默认）：
    Alt+Z  上一页
    Alt+C  下一页
    Alt+V  老板键（显示/隐藏）
    Alt+B  书架
    Alt+G  章节跳转
    Alt+S  设置

书本目录：与脚本同目录的 books/ 文件夹，放入 .txt 即可。
"""
import os
import shutil
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog
import tkinter.font as tkfont

from moyu_core import (APP_DIR, BOOKS_DIR, CONFIG_PATH, PROGRESS_PATH,
                       DEFAULT_CONFIG, DEFAULT_FONT, HOTKEYS, IS_MAC, IS_WIN,
                       detect_encoding, parse_chapters, load_config, save_config,
                       load_progress, save_progress, font_choices, resolve_font,
                       open_folder)
from moyu_backend import create_backend

MAGIC_BG = "#010203"   # 透明魔术色：此颜色的像素完全透明且点击穿透


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

        # 平台后端：热键 / 托盘 / 光标 / 工作区 / 透明
        self.backend = create_backend(on_action=self._dispatch_action,
                                      on_log=self._log_err)
        # 心跳间隔：Windows 500ms 够用；macOS 需要更短，点击穿透才跟手
        self._tick_ms = 100 if IS_MAC else 500
        self._last_tick = time.time()
        self._tick_id = None
        self.ui_font = resolve_font(DEFAULT_FONT)  # 界面控件字体

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
        return load_config(CONFIG_PATH)

    def _save_config(self):
        save_config(self.config, CONFIG_PATH)

    def _load_progress(self):
        return load_progress(PROGRESS_PATH)

    def _save_progress(self):
        save_progress(self.progress, PROGRESS_PATH)

    # ---------- 阅读窗 ----------
    def _build_reader_window(self):
        token = self.backend.begin_window()
        w = tk.Toplevel(self.root)
        w.overrideredirect(True)
        # 先关联原生窗口（macOS 透明/穿透要用），再设置顶与透明
        self.backend.bind_window(w, token)
        self.backend.set_topmost(w, True)
        self.backend.make_transparent(w, MAGIC_BG)
        ww = self.config["win_width"]
        wh = self.config["win_height"]
        wx = self.config.get("win_x", int((w.winfo_screenwidth() - ww) / 2))
        wy = self.config.get("win_y", 60)
        w.geometry(f"{ww}x{wh}+{wx}+{wy}")
        w.attributes("-alpha", 1.0)
        self.read_win = w

        self.font_obj = tkfont.Font(
            family=resolve_font(self.config["font_family"]),
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
                          cursor="hand2", font=(self.ui_font, 9))
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
            family=resolve_font(self.config["font_family"]),
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
        open_folder(BOOKS_DIR)

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

        lb = tk.Listbox(win, font=(self.ui_font, 10))
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
        tk.Label(win, text="字体：", font=(self.ui_font, 10)).pack(anchor="w", **pad)
        font_var = tk.StringVar(value=c["font_family"])
        fonts = font_choices()
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

        tk.Label(win, text="文字颜色：", font=(self.ui_font, 10)).pack(anchor="w", **pad)
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
                 font=(self.ui_font, 9), fg="#666666",
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
        # 使用工作区（避开任务栏 / Dock）
        wa_x, wa_y, wa_w, wa_h = self.backend.work_area()
        if abs(x - wa_x) < SNAP:
            x = wa_x
        elif abs((wa_x + wa_w) - (x + w)) < SNAP:
            x = wa_x + wa_w - w
        if abs(y - wa_y) < SNAP:
            y = wa_y
        elif abs((wa_y + wa_h) - (y + h)) < SNAP:
            y = wa_y + wa_h - h
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
        self.backend.start()
        # 托盘（Windows）/ 菜单栏图标（macOS）必须在 UI 线程创建
        self.backend.create_tray(APP_DIR)
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
            now = time.time()
            if self.read_win.winfo_viewable():
                # 面板打开时不自动隐藏；显示后 3 秒宽限期内也不隐藏（防瞬隐）
                if self._any_panel_open() or now - self._show_time < 3:
                    self._away_time = 0.0
                else:
                    pt_x, pt_y = self.backend.cursor_pos()
                    rx = self.read_win.winfo_x()
                    ry = self.read_win.winfo_y()
                    rw = self.read_win.winfo_width()
                    rh = self.read_win.winfo_height()
                    inside = rx <= pt_x <= rx + rw and ry <= pt_y <= ry + rh
                    if inside:
                        # 光标在文字上：永不隐藏
                        self._away_time = 0.0
                    elif now - self._last_activity < self.config["auto_hide_delay"]:
                        # 刚翻过页（在设定的隐藏时间内）：暂不隐藏，重新计时
                        self._away_time = 0.0
                    else:
                        # 累计真实经过时间（macOS 心跳更短，不能写死 0.5）
                        self._away_time += max(0.0, now - self._last_tick)
                        if self._away_time >= self.config["auto_hide_delay"]:
                            self.hide_reader(by_auto=True)
            else:
                self._away_time = 0.0
            # macOS：按光标位置动态切换点击穿透
            if IS_MAC:
                self._update_click_through()
            # 后端（热键线程）排队的动作，统一在这里转到 UI 线程执行
            for name in self.backend.poll_actions():
                self._dispatch_action(name)
        except Exception:
            pass
        self._last_tick = time.time()
        try:
            self._tick_id = self.root.after(self._tick_ms, self._auto_hide_tick)
        except Exception:
            pass

    def _update_click_through(self):
        """macOS 专用：光标在文字/工具条上时可交互，否则穿透到下层应用。"""
        rx = self.read_win.winfo_x()
        ry = self.read_win.winfo_y()
        rects = [(rx, ry, self.read_win.winfo_width(), self.read_win.winfo_height())]
        self.backend.update_click_through(self.read_win, rects)

    def _dispatch_action(self, name):
        """后端回调（热键 / 托盘菜单）：统一切到 UI 线程执行。"""
        actions = {
            "prev": lambda: self.turn_page(False),
            "next": lambda: self.turn_page(True),
            "boss": self.toggle_boss,
            "books": self.show_bookshelf,
            "chapters": self.show_chapters,
            "settings": self.show_settings,
            "move": self.toggle_move_mode,
            "quit": self.quit_app,
        }
        act = actions.get(name)
        if act is None:
            return
        try:
            self.root.after(0, act)
        except Exception:
            pass

    def _log_err(self, msg):
        try:
            with open(os.path.join(APP_DIR, "error.log"), "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        except Exception:
            pass

    def quit_app(self):
        self._running = False
        try:
            if getattr(self, "_tick_id", None):
                self.root.after_cancel(self._tick_id)
                self._tick_id = None
        except Exception:
            pass
        try:
            self.backend.stop()
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
