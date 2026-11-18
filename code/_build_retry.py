# -*- coding: utf-8 -*-
"""
_build_retry.py —— 目标 docx 被其它进程占用时的安全重建：
先构建到 论文/_pending.docx，再在 90 秒内循环尝试原子替换。
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import build_paper_p1 as bp  # noqa: E402

TARGET = bp.OUT
TMP = os.path.join(os.path.dirname(TARGET), '_pending.docx')

bp.OUT = TMP
out = bp.build()
print('临时文件已生成：', out, os.path.getsize(out) // 1024, 'KB')

ok = False
for i in range(45):
    try:
        os.replace(TMP, TARGET)
        ok = True
        print('第 %d 次尝试：替换成功' % (i + 1))
        break
    except PermissionError as e:
        time.sleep(2)
print('替换结果：', 'OK' if ok else 'FAILED（目标仍被占用）')
if not ok and os.path.exists(TMP):
    print('保留临时文件：', TMP)
sys.exit(0 if ok else 2)
