# 摸鱼小说阅读器 MoYu Reader

Windows / macOS 双平台的**悬浮式小说阅读器**。文字浮在桌面上，背景完全透明、鼠标点击穿透、永远置顶；
用全局热键翻页 / 老板键隐藏 / 跳章节 / 开书架 / 改设置，鼠标移开自动隐藏。

Windows 版**纯标准库实现，无任何第三方依赖**；macOS 版额外需要 PyObjC（系统 API 桥接）。

## 特性

- **透明悬浮**：正文直接浮在桌面上，背景像素完全透明且点击穿透，不影响你操作下面的窗口
- **全局置顶**：永远显示在其他窗口之上
- **全局热键**：Alt 组合键翻页 / 老板键 / 章节 / 书架 / 设置，不抢鼠标焦点
- **自动隐藏**：光标移开超过设定秒数自动隐藏，移回去自动恢复（光标在文字上时永不隐藏）
- **老板键**：一键隐藏 / 显示
- **托盘 / 菜单栏图标**：Windows 是系统托盘（左键切换显隐、右键菜单），macOS 是菜单栏图标
- **章节解析**：自动识别「第 X 章 / 回 / 节 / 卷 / 集 / 部」，支持跳转
- **进度保存**：每本书记住读到哪，下次自动续读
- **大文件无压力**：打开时解码一次全文，之后翻页是纯内存切片。22 MB / 811 万字的书加载约 0.33 秒，常驻内存约 37 MB

## 环境要求

### Windows

- Windows 7+
- Python 3.10+（开发环境为 Python 3.14）
- 无需安装任何第三方包

### macOS

- macOS 10.14+（Apple Silicon / Intel 都行）
- Python 3.9+，且带 Tk 支持（python.org 官方包自带；Homebrew 版需 `brew install python-tk`）
- 需要 PyObjC 与 pynput：`pip3 install -r requirements-mac.txt`
- **全局热键需要授权一次**：首次启动后到「系统设置 → 隐私与安全性 → 辅助功能」里把
  你的 Python（终端 / python3）打开，然后重启阅读器。不授权也能正常阅读，只是热键不响应

## 快速开始

### Windows

**方式一：双击 `start_reader.bat`**

**方式二：命令行**

```bat
pythonw moyu_reader.py
```

用 `pythonw` 启动不会有控制台窗口。

### macOS

**方式一：一键安装 + 体检**

```bash
cd moyu-reader
bash setup_mac.sh
```

脚本会自动建虚拟环境、装 PyObjC、跑一遍环境体检。

**方式二：直接启动**

双击 `start_reader_mac.command`（首次会自动装依赖）。

> macOS 提示「无法打开，因为来自身份不明的开发者」时：
> 在 Finder 里右键该文件 → 打开 → 确认打开；
> 或执行 `xattr -d com.apple.quarantine start_reader_mac.command`。

**方式三：命令行**

```bash
python3 moyu_reader.py
```

**排查问题**：跑 `python3 mac_doctor.py`，会逐项检查 Tk、PyObjC、pynput、辅助功能授权、屏幕坐标、透明窗口、点击穿透、菜单栏图标能否正常工作。

启动后把 `.txt` 小说丢进 `books/` 目录，按 **Alt+B** 打开书架，双击书名即可开始阅读。

## 快捷键

| 快捷键 | 作用 |
| --- | --- |
| `Alt+Z` | 上一页 |
| `Alt+C` | 下一页 |
| `Alt+V` | 老板键（显示 / 隐藏） |
| `Alt+B` | 书架 |
| `Alt+G` | 章节跳转 |
| `Alt+S` | 设置 |
| `Alt+D` | 位置调整模式（拖动窗口，结束时写回位置） |

## 鼠标操作

| 操作 | 效果 |
| --- | --- |
| 左键拖动 | 移动阅读窗 |
| 滚轮 | 翻页 |
| 双击 | 下一章 / 未打开书时打开书架 |
| 右键 | 显示 / 隐藏工具条 |

## 目录结构

```
moyu-reader/
├─ moyu_reader.py      主程序，唯一入口（Windows / macOS 共用界面）
├─ moyu_core.py        平台无关：编码识别、章节解析、配置与进度读写
├─ moyu_backend.py     平台后端入口 + Windows 实现（Win32 热键 / 托盘）
├─ moyu_backend_mac.py macOS 实现（pynput 热键 / NSStatusItem / 透明穿透）
├─ mac_doctor.py       macOS 环境体检脚本
├─ split_novel.py      辅助工具：把大 TXT 按 2MB 拆成多份
├─ start_reader.bat    Windows 启动器：无控制台窗口
├─ setup_mac.sh        macOS 一键安装 + 体检
├─ start_reader_mac.command  macOS 启动器（可双击）
├─ requirements-mac.txt      macOS 依赖（PyObjC + pynput）
├─ app_icon.ico        托盘图标
├─ LICENSE             MIT 许可证
├─ .gitignore
├─ books/              书籍目录，放 *.txt 即出现在书架（内容不入库）
├─ config.json         UI 配置，运行时自动生成
└─ progress.json       阅读进度，运行时自动生成
```

`config.json` 和 `progress.json` 都在运行时自动生成，已在 `.gitignore` 中排除。

## 两端差异

| 能力 | Windows | macOS |
| --- | --- | --- |
| 透明背景 | Tk `-transparentcolor` 魔术色，像素级 | NSWindow `clearColor` + `opaque=NO` |
| 点击穿透 | 魔术色天然穿透 | `ignoresMouseEvents`，按光标位置动态开关 |
| 全局热键 | Win32 `RegisterHotKey` | pynput `GlobalHotKeys`（需辅助功能授权） |
| 托盘 / 菜单栏 | 原生 `Shell_NotifyIcon` | `NSStatusItem` + `NSMenu` |
| 可用工作区 | `GetSystemMetrics(SM_CXWORKAREA)` | `NSScreen.visibleFrame`（自动避开 Dock 与菜单栏） |
| 中文字体 | 微软雅黑 | 苹方（配置里的字体本机不存在时自动回退） |

## 书籍格式

- 放在 `books/` 下的 `.txt` 文件
- 编码自动识别，顺序为 `UTF-8(BOM)` → `UTF-16` → `UTF-8`（坏字节 < 0.1%）→ `GB18030`，无需手动转码
- 章节标题形如 `第 12 章`、`第十二回`、`第三卷` 等，阿拉伯数字与中文数字都支持

## 设置项

在设置面板（`Alt+S`）里可以调整：字体、字号、每页字数、自动隐藏秒数、窗口高度、文字颜色。
配置保存后会立即生效并写入 `config.json`。

## License

[MIT](LICENSE) © 2026 chenmc729
