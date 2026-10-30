# -*- coding: utf-8 -*-
"""
macOS 环境体检
==============
在 Mac 上跑一遍，把「能不能跑、哪里不行」一次性说清楚。

用法：
    python3 mac_doctor.py

只读诊断，不改任何东西。
"""
import os
import platform
import subprocess
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

OK = "  [OK]  "
WARN = "  [!!]  "
FAIL = "  [XX]  "

results = []


def note(status, name, detail=""):
    results.append((status, name, detail))
    print(f"{status} {name}" + (f"  —— {detail}" if detail else ""))


print("=" * 62)
print("摸鱼阅读器 · macOS 环境体检")
print("=" * 62)

print("\n【1】系统与 Python")
print(f"  平台       : {platform.platform()}")
print(f"  macOS 版本 : {platform.mac_ver()[0]}")
print(f"  架构       : {platform.machine()}")
print(f"  Python     : {sys.version.split()[0]}  ({sys.executable})")
if sys.version_info < (3, 9):
    note(FAIL, "Python 版本过低", "需要 3.9+")
else:
    note(OK, "Python 版本")

print("\n【2】Tkinter（界面）")
try:
    import tkinter as tk
    import tkinter.font as tkfont
    root = tk.Tk()
    root.withdraw()
    note(OK, "tkinter 可用", f"Tk {root.tk.call('info', 'patchlevel')}")
    fams = set(tkfont.families())
    cjk = [f for f in ("PingFang SC", "苹方-简", "Songti SC", "STSong", "Heiti SC",
                       "STHeiti", "Kaiti SC", "Hiragino Sans GB")
           if f in fams]
    note(OK if cjk else WARN, "中文字体",
         "、".join(cjk) if cjk else "没找到常见中文字体，界面可能显示方块")
    root.destroy()
except Exception as e:
    note(FAIL, "tkinter 不可用", f"{e!r} —— 装 python.org 版本，或 brew install python-tk")
    root = None

print("\n【3】PyObjC（Cocoa 桥）")
try:
    import objc
    from AppKit import NSApp, NSColor, NSStatusBar, NSEvent, NSScreen
    from Foundation import NSObject
    note(OK, "objc / AppKit / Foundation")
except Exception as e:
    note(FAIL, "PyObjC 不可用", f"{e!r} —— pip3 install -r requirements-mac.txt")
    objc = None

print("\n【3b】pynput（全局热键）")
pynput_ok = False
try:
    from pynput import keyboard
    note(OK, "pynput 可用")
    pynput_ok = True
except Exception as e:
    note(FAIL, "pynput 不可用", f"{e!r} —— pip3 install pynput")

print("\n【3c】辅助功能授权（全局热键需要）")
try:
    from ApplicationServices import AXIsProcessTrusted
    trusted = bool(AXIsProcessTrusted())
    if trusted:
        note(OK, "已获得辅助功能授权", "全局热键可用")
    else:
        note(WARN, "尚未获得辅助功能授权",
             "去「系统设置 → 隐私与安全性 → 辅助功能」里把你的 Python "
             "（终端 / python3）打开，然后重启阅读器。不授权也能用鼠标操作，"
             "只是全局热键没反应")
except Exception as e:
    note(WARN, "无法查询授权状态", f"{e!r}")

print("\n【4】屏幕与坐标")
try:
    from AppKit import NSScreen
    scr = NSScreen.mainScreen()
    frame, vis = scr.frame(), scr.visibleFrame()
    note(OK, "主屏幕", f"frame={frame.size.width:.0f}x{frame.size.height:.0f} "
                       f"visible={vis.size.width:.0f}x{vis.size.height:.0f}")
    if len(NSScreen.screens()) > 1:
        note(WARN, "检测到多显示器", f"{len(NSScreen.screens())} 块，"
                                     "窗口坐标以主屏为基准，拖到副屏可能偏移")
    p = NSEvent.mouseLocation()
    note(OK, "光标位置", f"Cocoa=({p.x:.0f}, {p.y:.0f}) 左下原点")
except Exception as e:
    note(FAIL, "屏幕信息读取失败", repr(e))

print("\n【5】透明窗口 + 点击穿透（核心能力）")
if root is not None and objc is not None:
    try:
        import tkinter as tk
        from AppKit import NSApp, NSColor
        r2 = tk.Tk()
        r2.withdraw()
        before = {w.windowNumber() for w in NSApp.windows()}
        top = tk.Toplevel(r2)
        top.overrideredirect(True)
        top.configure(bg="#010203")
        top.geometry("400x60+100+100")
        top.update_idletasks()
        r2.update()
        after = [w for w in NSApp.windows() if w.windowNumber() not in before]
        if not after:
            note(WARN, "未找到新建的 NSWindow",
                 "窗口编号差集为空，将退回 winfo id 指针方式")
        else:
            nswin = after[0]
            note(OK, "找到 NSWindow", f"windowNumber={nswin.windowNumber()}")
            nswin.setBackgroundColor_(NSColor.clearColor())
            nswin.setOpaque_(False)
            nswin.setHasShadow_(False)
            note(OK, "透明设置成功", "clearColor + opaque=NO")
            nswin.setIgnoresMouseEvents_(True)
            note(OK, "点击穿透可用", "setIgnoresMouseEvents_(True)")
            nswin.setIgnoresMouseEvents_(False)
        wid = int(top.winfo_id())
        note(WARN, "winfo id 形态", f"{wid} "
                 + ("（像指针，可作兜底）" if wid > 0x100000 else "（是窗口编号，不能当指针用）"))
        top.destroy()
        r2.destroy()
    except Exception as e:
        note(FAIL, "透明窗口测试失败", repr(e))
        traceback.print_exc()
else:
    note(WARN, "跳过", "Tkinter 或 PyObjC 不可用")

print("\n【6】全局热键注册（pynput）")
if pynput_ok:
    try:
        from pynput import keyboard

        fired = []
        hk = keyboard.GlobalHotKeys({"<alt>+z": lambda: fired.append("z")})
        hk.start()
        import time
        time.sleep(0.5)
        hk.stop()
        note(OK, "GlobalHotKeys 启动成功",
             "请实际按一下 Option+Z 看是否触发（需要辅助功能授权）")
    except Exception as e:
        note(FAIL, "GlobalHotKeys 启动失败", repr(e))
else:
    note(WARN, "跳过", "pynput 不可用")

print("\n【7】菜单栏图标")
if objc is not None:
    try:
        from AppKit import NSStatusBar, NSMenu, NSMenuItem, NSVariableStatusItemLength
        item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        item.button().setTitle_("摸")
        menu = NSMenu.alloc().init()
        mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("测试", "fire:", "")
        menu.addItem_(mi)
        item.setMenu_(menu)
        note(OK, "NSStatusItem 可创建", "菜单栏右侧会出现「摸」字样")
        NSStatusBar.systemStatusBar().removeStatusItem_(item)
    except Exception as e:
        note(FAIL, "NSStatusItem 失败", repr(e))

print("\n【8】目录")
books = os.path.join(HERE, "books")
note(OK if os.path.isdir(books) else WARN, "books 目录",
     books if os.path.isdir(books) else "不存在，程序会自动创建")
cfg = os.path.join(HERE, "config.json")
note(OK if os.path.exists(cfg) else WARN, "config.json",
     "已存在" if os.path.exists(cfg) else "不存在，程序会自动生成默认配置")

print("\n" + "=" * 62)
n_ok = sum(1 for s, _, _ in results if s == OK)
n_warn = sum(1 for s, _, _ in results if s == WARN)
n_fail = sum(1 for s, _, _ in results if s == FAIL)
print(f"通过 {n_ok}  警告 {n_warn}  失败 {n_fail}")
if n_fail:
    print("\n有失败项，先按上面的提示处理，再跑一次体检。")
    sys.exit(1)
print("环境 OK，可以直接启动阅读器。")
print("=" * 62)
