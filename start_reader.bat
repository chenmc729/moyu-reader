@echo off
rem 启动摸鱼小说阅读器（无控制台窗口）
rem 依次尝试：PATH 中的 pythonw -> %LOCALAPPDATA% 安装目录 -> D:\Python\Python314

set "PYW="
for %%I in (pythonw.exe) do set "PYW=%%~$PATH:I"
if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\Python314\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\Python314\pythonw.exe"
if not defined PYW if exist "D:\Python\Python314\pythonw.exe" set "PYW=D:\Python\Python314\pythonw.exe"
if not defined PYW set "PYW=pythonw.exe"

start "" "%PYW%" "%~dp0moyu_reader.py"
