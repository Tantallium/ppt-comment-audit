"""用真实 Tk 布局验证盘符换行、缩放及选中范围；不扫描真实磁盘。"""
from datetime import datetime
import gc
import json
from pathlib import Path
import threading
import time
import tkinter as tk
import customtkinter as ctk
import types
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def verify_layout(module, count, scaling):
    drives = [f'{chr(65 + i)}:\\' for i in range(count)]
    ctk.set_widget_scaling(scaling)
    root = ctk.CTk()
    root.withdraw()
    root.attributes('-alpha', 0)
    measurements = []
    received = []
    called = threading.Event()

    def scan(roots, output, cancelled, notify, **options):
        received.extend(roots)
        called.set()
        return dict(state='完成', checked=0, counts={key: 0 for key in module.LABELS})

    def exercise():
        root.deiconify()
        root.update()
        choices = root.audit_app.drive_buttons
        assert [w.cget('text') for w in choices] == drives
        if choices:
            choices[-1].invoke()
        for width, height in [(1180, 780), (820, 640), (1440, 900), (820, 640)]:
            root.geometry(f'{width}x{height}')
            root.update()
            rows = set()
            for index, choice in enumerate(choices):
                assert choice.winfo_ismapped(), (count, scaling, width, 'unmapped', index)
                assert choice.winfo_width() >= choice.winfo_reqwidth(), (count, scaling, width, 'clipped width', index)
                assert choice.winfo_x() >= 0
                assert choice.winfo_x() + choice.winfo_width() <= choice.master.winfo_width()
                assert root.audit_app.options[index][1].get() == (index != count - 1)
                rows.add(choice.winfo_y())
            start = root.audit_app.start_button
            assert start.winfo_ismapped() and start.winfo_rooty() + start.winfo_height() <= root.winfo_rooty() + root.winfo_height(), (count, scaling, width, 'start clipped')
            measurements.append(dict(width=width, height=height, rows=len(rows), all_drives_visible=True))
        if count == 26:
            assert measurements[1]['rows'] > 1
            assert measurements[2]['rows'] <= measurements[1]['rows']
        if count > 1:
            start.invoke()
            limit = time.monotonic() + 2
            while not called.is_set() and time.monotonic() < limit:
                root.update()
            assert called.is_set() and received == drives[:-1]

    root.mainloop = exercise
    try:
        # 本测试只核对选择范围；线程和关闭流程由 test_audit_fixes 覆盖。
        inline_thread = lambda target, args, daemon: types.SimpleNamespace(start=lambda: target(*args))
        with patch.object(module, 'fixed_drives', return_value=drives), \
             patch.object(module, 'scan', side_effect=scan), \
             patch.object(module.threading, 'Thread', side_effect=inline_thread):
            module.launch_gui(root)
    finally:
        for callback in root.tk.call('after', 'info'):
            root.tk.call('after', 'cancel', callback)
        root.destroy()
        gc.collect()
    return dict(count=count, scaling=scaling, sizes=measurements, selection_preserved=True)


if __name__ == '__main__':
    results = []
    for label, relative in [('脚本版', 'ppt_audit.py'), ('便携版源码', '便携版打包/源码/ppt_audit.py')]:
        path = HERE / relative
        module = types.ModuleType('layout_test')
        module.__file__ = str(path)
        exec(compile(path.read_text(encoding='utf-8'), str(path), 'exec'), module.__dict__)
        for scaling in [1.0, 1.25, 1.5]:
            for count in [0, 1, 3, 6, 10, 16, 26]:
                results.append(dict(version=label, **verify_layout(module, count, scaling)))
    path = HERE / '验证记录' / ('盘符换行回归-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.json')
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(passed=True, cases=len(results), window_layout_checks=sum(len(r['sizes']) for r in results), report=str(path)), ensure_ascii=False))
