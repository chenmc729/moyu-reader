# -*- coding: utf-8 -*-
"""
摸鱼小说阅读器 —— 平台后端
===========================
把系统差异隔离在这一层：全局热键 / 托盘图标 / 鼠标位置 / 可用工作区 /
窗口透明 / 点击穿透。

Windows 走 Win32（ctypes）；macOS 走 PyObjC（见 moyu_backend_mac.py）。
上层 UI 只认 Backend 的接口，两边行为一致。
"""
import os
import sys
import threading
import time

IS_WIN = sys.platform == "win32"

if IS_WIN:
    import ctypes
    import ctypes.wintypes as wt

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    shell32 = ctypes.windll.shell32

    MOD_ALT = 0x0001
    WM_HOTKEY = 0x0312

    # 托盘相关常量
    WM_USER = 0x0400
    WM_TRAYICON = WM_USER + 20
    WM_RBUTTONUP = 0x0205
    WM_LBUTTONUP = 0x0202
    NIM_ADD, NIM_DELETE = 0, 2
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
    user32.LoadImageW.restype = wt.HANDLE
    user32.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT,
                                  ctypes.c_int, ctypes.c_int, wt.UINT]
    user32.DestroyIcon.argtypes = [wt.HICON]
    kernel32.GetModuleHandleW.restype = wt.HMODULE
    kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class Backend:
    """平台后端接口。子类实现各系统差异。"""

    name = "base"

    def __init__(self, on_action=None, on_log=None):
        # on_action(动作名)：在 UI 线程里执行
        self._on_action = on_action or (lambda name: None)
        self._on_log = on_log or (lambda msg: None)

    # -- 生命周期 --
    def start(self):
        """启动热键监听等后台设施。"""

    def stop(self):
        """停止后台设施。"""

    def poll_actions(self):
        """取回后端排队等待在 UI 线程执行的动作名列表。

        后台线程（热键监听）不能直接碰 Tk，只能排队，由 UI 线程取走。
        """
        return []

    # -- 系统信息 --
    def cursor_pos(self):
        """鼠标屏幕坐标 (x, y)，左上角为原点。"""
        return 0, 0

    def work_area(self):
        """可用工作区 (x, y, w, h)，左上角为原点。"""
        return 0, 0, 1920, 1080

    # -- 窗口 --
    def begin_window(self):
        """创建 Tk 窗口前调用，返回一个快照 token（用于事后关联原生窗口）。"""
        return None

    def bind_window(self, win, token):
        """创建后调用：把 Tk 窗口与平台原生窗口关联（透明 / 穿透要用）。"""

    def make_transparent(self, win, magic_bg):
        """让窗口背景透明；返回 True 表示已生效。"""
        return False

    def set_click_through(self, win, on):
        """鼠标穿透开关；不支持则忽略。"""

    def update_click_through(self, win, rects):
        """按光标位置动态切换穿透；rects 为屏幕坐标矩形列表。"""

    def set_topmost(self, win, on):
        """窗口置顶。"""
        try:
            win.attributes("-topmost", bool(on))
        except Exception:
            pass

    # -- 其它 --
    def create_tray(self, app_dir):
        """创建托盘 / 菜单栏图标。"""
        return None


class WinBackend(Backend):
    """Windows 后端：Win32 全局热键 + 原生托盘图标。"""

    name = "windows"

    def __init__(self, on_action=None, on_log=None):
        super().__init__(on_action, on_log)
        self._tray_hwnd = None
        self._nid = None
        self._tray_menu = None
        self._tray_wndproc_ref = None
        self._tray_icon = None
        self._menu_close_time = 0.0
        self._running = True
        self._tray_lock = threading.Lock()
        self._app_dir = os.path.dirname(os.path.abspath(__file__))

    # ---------- 热键 ----------
    def start(self):
        t = threading.Thread(target=self._hotkey_loop, daemon=True)
        t.start()

    def stop(self):
        self._running = False
        for i in range(1, len(HOTKEYS) + 1):
            try:
                user32.UnregisterHotKey(None, i)
            except Exception:
                pass

    def _hotkey_loop(self):
        from moyu_core import HOTKEYS
        try:
            self._create_tray_window()  # 托盘窗口挂在热键线程，消息循环一起处理
        except Exception as e:
            self._on_log(f"tray create failed: {e!r}")
        for idx, (_name, _disp, vk, _pk) in enumerate(HOTKEYS, start=1):
            user32.RegisterHotKey(None, idx, MOD_ALT, vk)
        msg = wt.MSG()
        while self._running:
            if user32.GetMessageW(ctypes.byref(msg), None, 0, 0) <= 0:
                break
            if msg.message == WM_HOTKEY:
                self._dispatch_hotkey(msg.wParam)
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _dispatch_hotkey(self, hk_id):
        from moyu_core import HOTKEYS
        names = [h[0] for h in HOTKEYS]
        if 1 <= hk_id <= len(names):
            self._on_action(names[hk_id - 1])

    # ---------- 系统信息 ----------
    def cursor_pos(self):
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y

    def work_area(self):
        # SM_CXWORKAREA / SM_CYWORKAREA：去掉任务栏后的可用区尺寸
        return 0, 0, user32.GetSystemMetrics(61), user32.GetSystemMetrics(62)

    # ---------- 窗口 ----------
    def make_transparent(self, win, magic_bg):
        try:
            win.configure(bg=magic_bg)
            win.attributes("-transparentcolor", magic_bg)
            return True
        except Exception as e:
            self._on_log(f"transparentcolor failed: {e!r}")
            return False

    # ---------- 托盘 ----------
    def create_tray(self, app_dir):
        try:
            self._create_tray_window()
        except Exception as e:
            self._on_log(f"tray create failed: {e!r}")
    def _create_tray_window(self):
        with self._tray_lock:
            if self._tray_hwnd:
                return  # 已创建过，别重复加图标
            wc = WNDCLASSEXW()
            wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
            wc.lpfnWndProc = self._tray_wndproc_ref = WNDPROC(self._tray_wndproc)
            wc.hInstance = kernel32.GetModuleHandleW(None)
            wc.lpszClassName = "MoYuTrayWnd"
            user32.RegisterClassExW(ctypes.byref(wc))
            self._tray_hwnd = user32.CreateWindowExW(
                0, "MoYuTrayWnd", "", 0, 0, 0, 0, 0,
                None, None, wc.hInstance, None)
            self._add_tray_icon(self._app_dir)

    def _add_tray_icon(self, app_dir):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._tray_hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAYICON
        icon_path = os.path.join(app_dir, "app_icon.ico")
        if os.path.exists(icon_path):
            # 从 .ico 文件加载（LR_LOADFROMFILE）
            self._tray_icon = user32.LoadImageW(
                None, icon_path, 1, 32, 32, 0x10)
        else:
            self._tray_icon = user32.LoadIconW(None, IDI_APPLICATION)
        nid.hIcon = self._tray_icon
        nid.szTip = "摸鱼阅读器"
        self._nid = nid
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))

    def _remove_tray_icon(self):
        if self._nid is not None:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
            self._nid = None
        if self._tray_icon:
            try:
                user32.DestroyIcon(self._tray_icon)
            except Exception:
                pass
            self._tray_icon = None

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
                    self._on_log(f"tray menu failed: {e!r}")
            elif action == WM_LBUTTONUP:
                # 防误触：菜单刚关闭时，忽略松键（防止选中菜单项后残留的左键松开触发切换）
                if time.time() - self._menu_close_time < 0.4:
                    self._on_log(f"WM_LBUTTONUP ignored (menu just closed, "
                                 f"dt={time.time()-self._menu_close_time:.2f}s)")
                    return user32.DefWindowProcW(hwnd, msg, wp, lp)
                self._on_log("WM_LBUTTONUP -> toggle_boss")
                self._on_action("boss")
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    def _show_tray_menu(self, x, y):
        """Win32 原生弹出菜单：定位准确、点击外部自动关闭、同步阻塞"""
        MF_STRING, MF_SEPARATOR = 0x0, 0x800
        TPM_RIGHTBUTTON, TPM_RETURNCMD = 0x2, 0x0100
        items = [
            (1, "显示/隐藏阅读窗", "boss"),
            (2, "书架", "books"),
            (3, "设置", "settings"),
            (None, None, None),          # 分隔线
            (4, "退出", "quit"),
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
        self._on_log(f"menu closed, cmd={cmd}")
        dispatched = False
        for i, _, action in items:
            if i is not None and cmd == i:
                self._on_log(f"dispatch item {i}: {action}")
                dispatched = True
                try:
                    self._on_action(action)
                except Exception as e:
                    self._on_log(f"dispatch failed: {e!r}")
        if not dispatched:
            self._on_log("no item matched (cmd=0 or unknown)")


def create_backend(on_action=None, on_log=None):
    """按平台创建后端。"""
    if IS_WIN:
        return WinBackend(on_action, on_log)
    try:
        from moyu_backend_mac import MacBackend
        return MacBackend(on_action, on_log)
    except Exception as e:
        raise SystemExit(
            "macOS 版需要 PyObjC，请先执行：\n"
            "    pip3 install -r requirements-mac.txt\n"
            f"（导入失败：{e!r}）")
