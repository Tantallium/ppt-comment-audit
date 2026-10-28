"""验证三个页面的对齐、按钮边界与系统缩放。"""
import json
from pathlib import Path
import tkinter as tk
from types import SimpleNamespace

import customtkinter as ctk
import ppt_audit
from md3_ui import AuditApp, C

BASE = Path(__file__).resolve().parent
root = ctk.CTk()
root.withdraw()
root.attributes('-alpha', 0)
app = AuditApp(root, SimpleNamespace(scan=ppt_audit.scan, fixed_drives=ppt_audit.fixed_drives,
                                    LABELS=ppt_audit.LABELS), BASE)
root.deiconify()
errors, checks = [], []
root.report_callback_exception = lambda *args: errors.append(str(args[1]))


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


try:
    for page in ['scan', 'results', 'help']:
        app.show_page(page)
        for width, height in [(820, 640), (1180, 780), (1440, 900)]:
            root.geometry(f'{width}x{height}')
            root.update()
            assert root.cget('fg_color') == C['surface']
            for button in [w for w in descendants(app.pages[page])
                           if isinstance(w, ctk.CTkButton) and w.winfo_ismapped()]:
                assert button.winfo_rootx() >= root.winfo_rootx()
                assert button.winfo_rootx() + button.winfo_width() <= root.winfo_rootx() + root.winfo_width()
            if page == 'scan':
                assert app.start_button.winfo_rooty() + app.start_button.winfo_height() <= root.winfo_rooty() + root.winfo_height()
                if app.wide:
                    assert app.scope_card.winfo_rooty() == app.progress_card.winfo_rooty()
                    gap = app.progress_card.winfo_rootx() - app.scope_card.winfo_rootx() - app.scope_card.winfo_width()
                    assert abs(gap - 16 * app.scope_card._get_widget_scaling()) <= 1
            if page == 'results':
                assert sum(app.tree.column(c, 'width') for c in app.tree['columns']) <= app.tree.winfo_width() + 2
                assert app.open_button.winfo_rooty() + app.open_button.winfo_height() <= root.winfo_rooty() + root.winfo_height()
            checks.append(dict(page=page, logical_window=[width, height],
                               widget_scale=app.main._get_widget_scaling(), aligned=True))
    assert not errors, errors
finally:
    for timer in root.tk.call('after', 'info'):
        root.after_cancel(timer)
    root.destroy()
out = BASE / '2026-10-28-MD3界面/对齐验证.json'
out.write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(dict(passed=True, checks=len(checks), report=str(out)), ensure_ascii=False))
