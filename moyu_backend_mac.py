# -*- coding: utf-8 -*-
"""
摸鱼小说阅读器 —— macOS 后端
=============================
用 PyObjC 对接 Cocoa，用 pynput 实现全局热键：

- 透明窗口：NSWindow 背景透明 + opaque=NO（对应 Windows 的 -transparentcolor）
- 点击穿透：NSWindow.setIgnoresMouseEvents_(True)，按光标位置动态开关
- 全局热键：pynput 的 GlobalHotKeys（Quartz 事件监听，需在「系统设置 →
  隐私与安全性 → 辅助功能」里授权一次）
- 菜单栏图标：NSStatusItem + NSMenu（对应 Windows 的托盘图标）
- 光标位置：NSEvent.mouseLocation
- 可用工作区：NSScreen.visibleFrame（自动避开 Dock 与菜单栏）

坐标系：Tk 左上角原点，Cocoa 左下角原点，这里统一转换。

注：早先想用 Carbon 的 RegisterEventHotKey，但它在 pyobjc 里缺少
InstallEventHandler / GetEventParameter（上游 issue #249 至今未修），
拿不到按键回调，因此改用 pynput。
"""
import os
import queue
import sys
import threading
import time

IS_MAC = sys.platform == "darwin"

if IS_MAC:
    try:
        import objc
        from AppKit import (NSApp, NSColor, NSMenu, NSMenuItem, NSStatusBar,
                            NSVariableStatusItemLength, NSEvent, NSScreen)
        from Foundation import NSObject
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "macOS 版需要 PyObjC，请执行：pip3 install -r requirements-mac.txt"
            f"（{e}）")
    _NSObjectBase = NSObject
else:
    # 非 macOS 上也要能 import（方便在别的机器上做静态检查）
    _NSObjectBase = object

from moyu_backend import Backend


class _StatusTarget(_NSObjectBase):
    """NSMenuItem 的动作接收者。

    注意：NSMenuItem 不会 retain 它的 target，所以调用方必须自己持有强引用，
    否则这个对象会被立刻释放，菜单点了没反应。
    """

    def initWithCallback_(self, cb):
        self = objc.super(_StatusTarget, self).init()
        if self is None:
            return None
        self._cb = cb
        return self

    def fire_(self, sender):
        try:
            self._cb()
        except Exception:
            pass


class MacBackend(Backend):
    """macOS 平台后端，接口与 moyu_backend.Backend 一致。"""

    name = "macos"

    def __init__(self, on_action=None, on_log=None):
        self._on_action = on_action or (lambda name: None)
        self._on_log = on_log or (lambda msg: None)
        self._running = True
        self._status_item = None
        self._menu = None
        self._status_target = None          # 必须自持强引用（NSMenuItem 不 retain target）
        self._ns_windows = {}               # id(tk widget) -> NSWindow
        self._pynput_hotkeys = None
        self._queue = queue.Queue()         # 热键线程 -> UI 线程的动作队列
        self._main_h = 1080.0
        self._transparent_ok = False

    # ---------- 生命周期 ----------
    def start(self):
        self._install_hotkeys()

    def stop(self):
        self._running = False
        self._stop_hotkeys()
        self._remove_status_item()

    # ---------- 动作队列 ----------
    def poll_actions(self):
        """取回后端排队等待在 UI 线程执行的动作名列表。"""
        out = []
        while True:
            try:
                out.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return out

    # ---------- 窗口关联（透明 / 穿透要用原生窗口） ----------
    def begin_window(self):
        """创建 Tk 窗口前调用，返回快照 token。"""
        try:
            return {w.windowNumber() for w in NSApp.windows()}
        except Exception:
            return None

    def bind_window(self, win, token):
        """创建后调用：把 Tk 窗口和对应的 NSWindow 关联起来。

        不去猜指针地址，而是比较创建前后的窗口编号集合 —— 绝对安全。
        """
        try:
            win.update_idletasks()
        except Exception:
            pass
        try:
            cur = NSApp.windows()
        except Exception:
            return
        if token is not None:
            new = [w for w in cur if w.windowNumber() not in token]
        else:
            new = []
        if len(new) == 1:
            self._ns_windows[id(win)] = new[0]
            return
        # 有多个新增时，按几何尺寸挑最接近的
        if new:
            try:
                tw = win.winfo_width()
                th = win.winfo_height()
            except Exception:
                tw = th = 0
            best, bestd = None, None
            for w in new:
                f = w.frame()
                d = abs(f.size.width - tw) + abs(f.size.height - th)
                if bestd is None or d < bestd:
                    best, bestd = w, d
            self._ns_windows[id(win)] = best
            return
        # 兜底：winfo id 若是 NSWindow / NSView 指针可直接拿到（指针值必然 > 1MB）
        nswin = self._ns_window_from_pointer(win)
        if nswin is not None:
            self._ns_windows[id(win)] = nswin

    def _ns_window_from_pointer(self, win):
        """macOS 上 Tk 的 winfo id 可能是 NSWindow 或 NSView 指针。

        小于 1MB 的值一定是窗口编号（不是指针），直接跳过，避免非法指针导致崩溃。
        """
        try:
            wid = int(win.winfo_id())
        except Exception:
            return None
        if wid < 0x100000:
            return None
        try:
            obj = objc.objc_object(wid)
            if hasattr(obj, "window"):     # NSView -> 取所属 NSWindow
                return obj.window()
            return obj                     # 本来就是 NSWindow
        except Exception as e:
            self._on_log(f"_ns_window_from_pointer failed: {e!r}")
            return None

    def _ns_window(self, win):
        return self._ns_windows.get(id(win))

    # ---------- 系统信息 ----------
    def _main_screen(self):
        try:
            return NSScreen.mainScreen()
        except Exception:
            return None

    def cursor_pos(self):
        """光标屏幕坐标 (x, y)，左上角为原点。"""
        try:
            p = NSEvent.mouseLocation()
            return int(p.x), int(self._flip_y(p.y))
        except Exception as e:
            self._on_log(f"cursor_pos failed: {e!r}")
            return 0, 0

    def _flip_y(self, mac_y):
        """Cocoa 左下原点 → Tk 左上原点。

        主屏高度必须运行时取（1080 / 982 / 1117 取决于显示器，不是常量）。
        """
        scr = self._main_screen()
        if scr is not None:
            try:
                self._main_h = scr.frame().size.height
            except Exception:
                pass
        return self._main_h - mac_y

    def work_area(self):
        """可用工作区 (x, y, w, h)，左上角为原点（自动避开 Dock 与菜单栏）。"""
        try:
            scr = self._main_screen()
            if scr is None:
                return 0, 0, 1920, 1080
            frame = scr.frame()
            vis = scr.visibleFrame()
            x = int(vis.origin.x - frame.origin.x)
            y = int(frame.size.height - (vis.origin.y - frame.origin.y) - vis.size.height)
            return x, y, int(vis.size.width), int(vis.size.height)
        except Exception as e:
            self._on_log(f"work_area failed: {e!r}")
            return 0, 0, 1920, 1080

    # ---------- 窗口透明 / 穿透 ----------
    def make_transparent(self, win, magic_bg):
        """NSWindow 背景设为透明。成功返回 True。"""
        nswin = self._ns_window(win)
        if nswin is None:
            self._on_log("make_transparent: 未找到对应的 NSWindow")
            return False
        try:
            nswin.setBackgroundColor_(NSColor.clearColor())
            nswin.setOpaque_(False)
            nswin.setHasShadow_(False)
            nswin.setReleasedWhenClosed_(False)
            self._transparent_ok = True
            return True
        except Exception as e:
            self._on_log(f"make_transparent failed: {e!r}")
            return False

    def set_click_through(self, win, on):
        """鼠标穿透开关。"""
        nswin = self._ns_window(win)
        if nswin is None:
            return
        try:
            nswin.setIgnoresMouseEvents_(bool(on))
        except Exception as e:
            self._on_log(f"set_click_through failed: {e!r}")

    def update_click_through(self, win, rects):
        """按光标位置动态切换穿透：光标在 rects 内则可交互，否则穿透。

        rects: [(x, y, w, h)]，屏幕坐标（左上角原点）。
        """
        nswin = self._ns_window(win)
        if nswin is None:
            return
        try:
            cx, cy = self.cursor_pos()
            inside = any(x <= cx <= x + w and y <= cy <= y + h for x, y, w, h in rects)
            nswin.setIgnoresMouseEvents_(not inside)
        except Exception as e:
            self._on_log(f"update_click_through failed: {e!r}")

    def set_topmost(self, win, on):
        """置顶：抬 NSWindow 层级（Tk 的 -topmost 在 macOS 上不可靠）。"""
        try:
            win.attributes("-topmost", bool(on))
        except Exception:
            pass
        nswin = self._ns_window(win)
        if nswin is None:
            return
        try:
            from AppKit import NSFloatingWindowLevel, NSStatusWindowLevel
            nswin.setLevel_(NSFloatingWindowLevel if on else NSStatusWindowLevel)
        except Exception as e:
            self._on_log(f"set_topmost failed: {e!r}")

    # ---------- 全局热键（pynput） ----------
    def _install_hotkeys(self):
        """用 pynput 注册全局热键。

        pynput 在独立线程里监听按键，回调不能直接碰 Tk，
        所以动作先进队列，由 UI 线程在心跳里取走。
        """
        try:
            from pynput import keyboard
        except Exception as e:
            self._on_log(f"pynput 不可用，全局热键不可用: {e!r} "
                         f"（pip3 install pynput）")
            return False

        from moyu_core import HOTKEYS

        mapping = {}
        for name, _disp, _vk, pk in HOTKEYS:
            mapping[pk] = (lambda n=name: self._queue.put(n))
        try:
            self._pynput_hotkeys = keyboard.GlobalHotKeys(mapping)
            self._pynput_hotkeys.start()
        except Exception as e:
            self._on_log(f"pynput 热键启动失败: {e!r} "
                         f"（可能需要在「系统设置 → 隐私与安全性 → 辅助功能」里授权）")
            self._pynput_hotkeys = None
            return False
        self._on_log("全局热键已启动 (pynput)")
        return True

    def _stop_hotkeys(self):
        try:
            if self._pynput_hotkeys is not None:
                self._pynput_hotkeys.stop()
        except Exception:
            pass
        self._pynput_hotkeys = None

    # ---------- 菜单栏图标（对应 Windows 托盘） ----------
    def create_tray(self, app_dir):
        try:
            self._remove_status_item()
            bar = NSStatusBar.systemStatusBar()
            item = bar.statusItemWithLength_(NSVariableStatusItemLength)
            # 标题用文字，省得再画图标
            try:
                item.button().setTitle_("摸")
                item.button().setToolTip_("摸鱼阅读器")
            except Exception:
                pass

            menu = NSMenu.alloc().init()
            # NSMenuItem 不 retain target —— 这里必须自己留着强引用
            self._status_target = _StatusTarget.alloc().initWithCallback_(self._on_action)
            for title, action in (("显示/隐藏阅读窗", "boss"), ("书架", "books"),
                                  ("设置", "settings")):
                mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, "fire:", "")
                mi.setTarget_(self._status_target)
                menu.addItem_(mi)
            menu.addItem_(NSMenuItem.separatorItem())
            mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("退出", "fire:", "")
            mi.setTarget_(self._status_target)
            menu.addItem_(mi)

            item.setMenu_(menu)
            self._status_item = item
            self._menu = menu
        except Exception as e:
            self._on_log(f"create_tray failed: {e!r}")

    def _remove_status_item(self):
        try:
            if self._status_item is not None:
                NSStatusBar.systemStatusBar().removeStatusItem_(self._status_item)
        except Exception:
            pass
        self._status_item = None
        self._menu = None
        self._status_target = None
