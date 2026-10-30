# -*- coding: utf-8 -*-
"""
小说 TXT 拆分工具
把大 TXT 文件拆成多个小文件（默认每个 2MB），方便放入 books 目录阅读。
用法: python split_novel.py <文件路径> [单文件大小MB，默认2]
"""
import sys
import os

def split_txt(file_path, max_mb=2):
    max_bytes = max_mb * 1024 * 1024

    if not os.path.exists(file_path):
        print(f"文件不存在: {file_path}")
        return

    # 检测编码
    with open(file_path, 'rb') as f:
        raw = f.read(65536)

    encoding = 'utf-8'
    if raw[:3] == b'\xef\xbb\xbf':
        encoding = 'utf-8-sig'
    elif raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        encoding = 'utf-16'
    else:
        # 优先尝试 UTF-8，允许极少量坏字节（<0.1%），失败再尝试 GB 系列
        try:
            text = raw.decode('utf-8', errors='replace')
            bad_ratio = text.count('�') / max(len(text), 1)
            if bad_ratio < 0.001:
                encoding = 'utf-8'
            else:
                encoding = 'gb18030'
        except Exception:
            encoding = 'gb18030'

    print(f"文件: {file_path}")
    print(f"编码: {encoding}")
    print(f"大小: {os.path.getsize(file_path) / 1024 / 1024:.1f} MB")

    with open(file_path, 'r', encoding=encoding, errors='replace') as f:
        content = f.read()

    total_chars = len(content)
    print(f"总字数: {total_chars}")

    if os.path.getsize(file_path) <= max_bytes:
        print("文件不大，无需拆分。")
        return

    # 按行拆分，尽量在段落边界断开
    lines = content.split('\n')
    base_name = os.path.splitext(file_path)[0]

    part = 1
    current_size = 0
    current_lines = []

    for line in lines:
        line_bytes = len(line.encode('utf-8', errors='replace')) + 1  # +1 for \n
        if current_size + line_bytes > max_bytes and current_lines:
            out_path = f"{base_name}_part{part}.txt"
            with open(out_path, 'w', encoding='utf-8-sig', errors='replace') as out:
                out.write('\n'.join(current_lines))
            print(f"  -> {os.path.basename(out_path)} ({current_size / 1024 / 1024:.1f} MB)")
            part += 1
            current_size = 0
            current_lines = []
        current_lines.append(line)
        current_size += line_bytes

    # 写最后一部分
    if current_lines:
        out_path = f"{base_name}_part{part}.txt"
        with open(out_path, 'w', encoding='utf-8-sig', errors='replace') as out:
            out.write('\n'.join(current_lines))
        print(f"  -> {os.path.basename(out_path)} ({current_size / 1024 / 1024:.1f} MB)")

    print(f"\n拆分完成！共 {part} 个文件。")
    print("把它们放入 books 文件夹即可阅读。")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: python split_novel.py <文件路径> [单文件大小MB，默认2]")
        sys.exit(1)

    fp = sys.argv[1]
    size = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0
    split_txt(fp, size)
