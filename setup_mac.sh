#!/bin/bash
# 摸鱼阅读器 · macOS 一键安装
# 用法：在「终端」里 cd 到本目录，执行  bash setup_mac.sh
#
# 做三件事：
#   1. 找一个带 Tk 的 python3
#   2. 建 .venv 虚拟环境并装 PyObjC
#   3. 跑一遍 mac_doctor.py 环境体检

set -u
cd "$(dirname "$0")"

echo "=============================================="
echo " 摸鱼阅读器 · macOS 安装"
echo "=============================================="
echo

# ---------- 1. 找 python ----------
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
    echo "!! 找不到带 Tk 支持的 python3"
    echo
    echo "两个办法，任选其一："
    echo "  A) 装 Homebrew 版："
    echo "       brew install python-tk"
    echo "  B) 装 python.org 官方版（自带 Tk）：https://www.python.org/downloads/macos/"
    echo
    echo "装完再跑一次本脚本。"
    exit 1
fi
echo "使用 Python: $PY ($("$PY" -V 2>&1))"

# ---------- 2. 虚拟环境 ----------
VENV=".venv"
VPY=""
if [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -c "import tkinter" >/dev/null 2>&1; then
    VPY="$VENV/bin/python"
    echo "复用已有虚拟环境 $VENV"
else
    echo "创建虚拟环境 $VENV ..."
    if ! "$PY" -m venv --clear "$VENV" 2>/dev/null; then
        echo "!! venv 创建失败"
        exit 1
    fi
    if ! "$VENV/bin/python" -c "import tkinter" >/dev/null 2>&1; then
        echo "!! 虚拟环境里没有 tkinter（系统 Python 常见问题）"
        echo "   改用系统 Python: brew install python-tk"
        exit 1
    fi
    VPY="$VENV/bin/python"
fi

# ---------- 3. 装依赖 ----------
if "$VPY" -c "import objc, AppKit, pynput" >/dev/null 2>&1; then
    echo "依赖已就绪"
else
    echo "安装依赖 ..."
    "$VPY" -m pip install --upgrade pip >/dev/null 2>&1
    if ! "$VPY" -m pip install -r requirements-mac.txt; then
        echo "!! 依赖安装失败"
        echo "   试着手动装: $VPY -m pip install -r requirements-mac.txt"
        exit 1
    fi
fi

echo
echo "=============================================="
echo " 安装完成，正在做环境体检 ..."
echo "=============================================="
"$VPY" mac_doctor.py
rc=$?

echo
if [ $rc -eq 0 ]; then
    echo "下一步：双击 start_reader_mac.command 启动"
else
    echo "体检有失败项，按上面提示处理后再试"
fi
exit $rc
