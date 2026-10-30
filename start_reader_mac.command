#!/bin/bash
# 摸鱼阅读器 · macOS 启动器
# 双击本文件即可启动（第一次会自动装依赖）。
#
# 如果 macOS 提示「无法打开，因为来自身份不明的开发者」：
#   在 Finder 里右键本文件 → 打开 → 确认打开
#   或者在终端执行一次：  xattr -d com.apple.quarantine start_reader_mac.command

cd "$(dirname "$0")"
LOG="reader.log"

PY=""
for cand in python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 \
             /usr/bin/python3 python3.13 python3.12 python3.11 python3.10; do
    if command -v "$cand" >/dev/null 2>&1; then
        if "$cand" -c "import tkinter" >/dev/null 2>&1; then
            PY="$(command -v "$cand")"
            break
        fi
    fi
done

if [ -z "$PY" ]; then
    echo "找不到带 Tk 的 python3，先执行 bash setup_mac.sh"
    echo
    read -r -p "按回车关闭..." _
    exit 1
fi

VPY=""
if [ -x ".venv/bin/python" ] && ".venv/bin/python" -c "import tkinter" >/dev/null 2>&1; then
    VPY=".venv/bin/python"
else
    VPY="$PY"
fi

if ! "$VPY" -c "import objc, AppKit, pynput" >/dev/null 2>&1; then
    echo "首次运行，正在安装依赖（约 1 分钟）..."
    "$VPY" -m pip install -r requirements-mac.txt || {
        echo "安装失败，请手动执行: $VPY -m pip install -r requirements-mac.txt"
        read -r -p "按回车关闭..." _
        exit 1
    }
fi

# 后台运行，日志写到 reader.log
nohup "$VPY" moyu_reader.py >> "$LOG" 2>&1 &
PID=$!
sleep 2

if ! kill -0 "$PID" 2>/dev/null; then
    echo "启动失败，日志尾部："
    tail -n 20 "$LOG"
    echo
    read -r -p "按回车关闭..." _
    exit 1
fi

echo "摸鱼阅读器已启动 (PID $PID)"
echo "  快捷键：Alt+Z/C 翻页 · Alt+V 老板键 · Alt+B 书架 · Alt+G 章节 · Alt+S 设置"
echo "  日志：$(pwd)/$LOG"
echo
echo "关闭方式：菜单栏右侧「摸」图标 → 退出"
read -r -p "按回车关闭本窗口（阅读器会继续在后台运行）..." _
