"""PPT 批注检查的 Material Design 3 桌面界面。"""
from datetime import datetime
import ctypes
from functools import lru_cache
import json
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont


VERSION = '1.4'
C = dict(surface='#F8FAFD', low='#F0F4F9', container='#E9EEF6', high='#E1E7EF',
         card='#FFFFFF', text='#1F1F1F', muted='#444746', outline='#747775',
         divider='#C4C7C5', primary='#0B57D0', on_primary='#FFFFFF',
         primary_container='#D3E3FD', on_primary_container='#0842A0',
         secondary_container='#E3E9F3', on_secondary_container='#3C4758',
         error='#B3261E', error_container='#F9DEDC',
         success='#146C2E', success_container='#C4EED0',
         warning='#7A4D00', warning_container='#FFE7B4')
FONT = 'Microsoft YaHei UI'
ASSETS = Path(__file__).resolve().parent / 'assets'
GLYPHS = dict(check='\ue5ca', scan='\ue8b6', results='\ue85d', help='\ue887',
              folder='\ue2c7', add='\ue145', close='\ue5cd', play='\ue037',
              stop='\ue047', report='\ue873', shield='\ue9e0', disk='\ue1db',
              arrow='\ue5c8', copy='\ue14d', launch='\ue89e', info='\ue88e',
              warning='\ue002', document='\ue24d')


@lru_cache(maxsize=96)
def icon(name, color, size=24):
    image = Image.new('RGBA', (size * 3, size * 3))
    font = ImageFont.truetype(str(ASSETS / 'MaterialIcons-Regular.ttf'), size * 3)
    ImageDraw.Draw(image).text((size * 1.5, size * 1.5), GLYPHS[name],
                              fill=color, font=font, anchor='mm')
    return ctk.CTkImage(image, size=(size, size))


def label(parent, text='', size=14, color=None, bold=False, **kwargs):
    kwargs.setdefault('font', (FONT, size, 'bold' if bold else 'normal'))
    kwargs.setdefault('text_color', color or C['text'])
    kwargs.setdefault('anchor', 'w')
    return ctk.CTkLabel(parent, text=text, **kwargs)


def wrap_label(widget, width):
    if not widget.winfo_ismapped():
        return
    width = max(160, round(width))
    if widget.cget('wraplength') != width:
        widget.configure(wraplength=width)


def scroll_area(parent):
    outer = ctk.CTkFrame(parent, fg_color=C['surface'], corner_radius=0)
    outer.grid_rowconfigure(0, weight=1)
    outer.grid_columnconfigure(0, weight=1)
    canvas = tk.Canvas(outer, bg=C['surface'], highlightthickness=0, borderwidth=0)
    canvas.grid(row=0, column=0, sticky='nsew')
    bar = ttk.Scrollbar(outer, orient='vertical', command=canvas.yview, style='MD3.Vertical.TScrollbar')
    bar.grid(row=0, column=1, sticky='ns')
    canvas.configure(yscrollcommand=bar.set)
    content = ctk.CTkFrame(canvas, fg_color=C['surface'], corner_radius=0)
    item = canvas.create_window((0, 0), window=content, anchor='nw')
    canvas.bind('<Configure>', lambda e: canvas.itemconfigure(item, width=e.width))
    tk.Frame.bind(content, '<Configure>', lambda _: canvas.configure(scrollregion=canvas.bbox('all')), add='+')

    def inside(widget):
        while widget is not None:
            if widget is outer:
                return True
            widget = getattr(widget, 'master', None)
        return False

    def wheel(event):
        if inside(parent.winfo_containing(event.x_root, event.y_root)):
            canvas.yview_scroll(-int(event.delta / 120) * 3, 'units')
            return 'break'

    def focus(event):
        if inside(event.widget) and content.winfo_height() > canvas.winfo_height():
            y = event.widget.winfo_rooty() - canvas.winfo_rooty()
            if y < 0 or y + event.widget.winfo_height() > canvas.winfo_height():
                offset = event.widget.winfo_rooty() - content.winfo_rooty()
                canvas.yview_moveto(max(0, offset - 16) / content.winfo_height())

    parent.winfo_toplevel().bind('<MouseWheel>', wheel, add='+')
    parent.winfo_toplevel().bind('<FocusIn>', focus, add='+')
    return outer, content


class Button(ctk.CTkButton):
    """圆角按钮，保留 Tab、空格、回车与可见焦点。"""
    def __init__(self, parent, text, command, kind='tonal', symbol=None, **kwargs):
        styles = {
            'filled': (C['primary'], C['on_primary'], '#0842A0'),
            'tonal': (C['primary_container'], C['on_primary_container'], '#C2D7F8'),
            'text': ('transparent', C['primary'], C['container']),
            'outlined': ('transparent', C['primary'], C['low']),
        }
        bg, fg, hover = styles[kind]
        options = dict(height=44, width=120, corner_radius=22, border_width=1 if kind == 'outlined' else 0,
                       border_color=C['outline'], fg_color=bg, text_color=fg, hover_color=hover,
                       text_color_disabled='#777D87', font=(FONT, 14), border_spacing=10)
        if symbol:
            options['image'] = icon(symbol, fg, 20)
        options.update(kwargs)
        super().__init__(parent, text=text, command=command, **options)
        self.normal_border = options['border_width']
        tk.Frame.configure(self, takefocus=1)
        tk.Frame.bind(self, '<FocusIn>', lambda _: self.configure(border_width=2, border_color=C['primary']))
        tk.Frame.bind(self, '<FocusOut>', lambda _: self.configure(border_width=self.normal_border, border_color=C['outline']))
        tk.Frame.bind(self, '<space>', self._key_invoke)
        tk.Frame.bind(self, '<Return>', self._key_invoke)

    def _key_invoke(self, _):
        self.invoke()
        return 'break'


class ElidedLabel(ctk.CTkLabel):
    """窄窗口内保留路径首尾；完整路径在结果详情中可复制。"""
    def __init__(self, parent, **kwargs):
        super().__init__(parent, text='', anchor='w', font=(FONT, 12),
                         text_color=C['muted'], **kwargs)
        self.full_text = ''
        tk.Frame.bind(self, '<Configure>', lambda _: self.refresh(), add='+')

    def set(self, text):
        self.full_text = str(text)
        self.refresh()

    def refresh(self):
        text = self.full_text
        limit = max(5, int(self.winfo_width() / self._get_widget_scaling()))
        font = self._font
        if not hasattr(font, 'measure'):
            import tkinter.font
            font = tkinter.font.Font(family=FONT, size=-12)
        if font.measure(text) > limit:
            left, right = 0, len(text)
            while left < right:
                mid = (left + right + 1) // 2
                candidate = text[:mid // 3] + '…' + text[-max(1, mid * 2 // 3):]
                if font.measure(candidate) <= limit:
                    left = mid
                else:
                    right = mid - 1
            text = text[:left // 3] + '…' + text[-max(1, left * 2 // 3):]
        if text != self.cget('text'):
            self.configure(text=text)


class AuditApp:
    def __init__(self, window, engine, base_dir):
        icon.cache_clear()
        self.window, self.engine, self.base_dir = window, engine, Path(base_dir)
        self.messages = queue.Queue()
        self.cancelled = threading.Event()
        self.state = dict(running=False, report=None, close_requested=False)
        self.options, self.drive_buttons, self.folders, self.scope_controls = [], [], [], []
        self.results, self.summary = [], None
        self.active_page = 'scan'
        self.filter_mode = '全部'
        self.drive_columns = None
        self.wide = None
        ctk.set_appearance_mode('light')
        window.title(f'PPT 文件检查 · v{VERSION}')
        window.iconbitmap(str(ASSETS / 'app.ico'))
        window.geometry('1180x780')
        window.minsize(820, 640)
        window.configure(**{'fg_color' if isinstance(window, ctk.CTk) else 'bg': C['surface']})
        window.grid_columnconfigure(1, weight=1)
        window.grid_rowconfigure(0, weight=1)
        self._build_navigation()
        self.main = ctk.CTkFrame(window, fg_color=C['surface'], corner_radius=0)
        self.main.grid(row=0, column=1, sticky='nsew', padx=(24, 24), pady=(24, 24))
        self.main.grid_rowconfigure(1, weight=1)
        self.main.grid_columnconfigure(0, weight=1)
        header = ctk.CTkFrame(self.main, fg_color='transparent')
        header.grid(row=0, column=0, sticky='ew', pady=(0, 24))
        header.grid_columnconfigure(0, weight=1)
        self.title = label(header, 'PPT 文件检查', 30, bold=True)
        self.title.grid(row=0, column=0, sticky='w')
        self.subtitle = label(header, '定位批注编号问题，让排查更清晰。', color=C['muted'])
        self.subtitle.grid(row=1, column=0, sticky='w', pady=(6, 0))
        badge = ctk.CTkFrame(header, fg_color=C['success_container'], corner_radius=16)
        badge.grid(row=0, column=1, rowspan=2, sticky='e', padx=(12, 0))
        label(badge, '本地 · 只读', 12, C['success'], image=icon('shield', C['success'], 16),
              compound='left', height=24).pack(padx=12, pady=4)
        self.pages = {}
        for key in ('scan', 'results', 'help'):
            page = ctk.CTkFrame(self.main, fg_color='transparent', corner_radius=0)
            self.pages[key] = page
        self._build_scan()
        self._build_results()
        self._build_help()
        self.show_page('scan')
        self.update_selection()
        window.protocol('WM_DELETE_WINDOW', self.close)
        window.bind('<Control-Return>', lambda _: self.start())
        window.bind('<Control-f>', self.focus_search)
        window.bind('<F1>', lambda _: self.show_page('help'))
        self.poll_id = window.after(100, self.poll)

    def _build_navigation(self):
        rail = ctk.CTkFrame(self.window, width=88, fg_color=C['low'], corner_radius=0)
        rail.grid(row=0, column=0, sticky='ns')
        rail.grid_propagate(False)
        rail.grid_rowconfigure(8, weight=1)
        self.brand_image = ctk.CTkImage(Image.open(ASSETS / 'app-icon.png'), size=(56, 56))
        label(rail, image=self.brand_image, width=56, height=56).grid(row=0, column=0, padx=16, pady=(24, 36))
        self.nav = {}
        for i, (key, text, symbol) in enumerate([('scan', '文件检查', 'scan'),
                                                ('results', '检查结果', 'results'),
                                                ('help', '使用说明', 'help')]):
            item = ctk.CTkFrame(rail, fg_color='transparent')
            item.grid(row=i + 1, column=0, padx=12, pady=(0, 20))
            button = Button(item, '', lambda k=key: self.show_page(k), 'text',
                            width=64, height=36, corner_radius=18,
                            image=icon(symbol, C['muted'], 24))
            button.pack()
            caption = label(item, text, 12, C['muted'], anchor='center')
            caption.pack(pady=(5, 0))
            caption.bind('<Button-1>', lambda _, k=key: self.show_page(k))
            self.nav[key] = (button, caption, symbol)
        label(rail, f'v{VERSION}', 12, C['muted'], anchor='center').grid(row=9, column=0, pady=24)

    def _build_scan(self):
        page = self.pages['scan']
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(0, weight=1)
        viewport, scroll = scroll_area(page)
        viewport.grid(row=0, column=0, sticky='nsew')
        scroll.grid_columnconfigure(0, weight=1)
        self.scan_grid = ctk.CTkFrame(scroll, fg_color='transparent', corner_radius=0)
        self.scan_grid.grid(row=0, column=0, sticky='ew')
        self.scope_card = ctk.CTkFrame(self.scan_grid, fg_color=C['card'], corner_radius=28)
        self.progress_card = ctk.CTkFrame(self.scan_grid, fg_color=C['low'], corner_radius=28)
        self.scope_card.grid_columnconfigure(0, weight=1)
        self.progress_card.grid_columnconfigure(0, weight=1)
        tk.Frame.bind(self.scan_grid, '<Configure>', self.layout_panels, add='+')
        heading = ctk.CTkFrame(self.scope_card, fg_color='transparent')
        heading.grid(row=0, column=0, sticky='ew', padx=24, pady=(24, 16))
        label(heading, '检查范围', 20, bold=True).pack(side='left')
        self.scope_count = label(heading, '', 12, C['muted'])
        self.scope_count.pack(side='right')
        row = ctk.CTkFrame(self.scope_card, fg_color='transparent')
        row.grid(row=1, column=0, sticky='ew', padx=24)
        label(row, '本地磁盘', 14, bold=True).pack(side='left')
        for text, value in [('清空', False), ('全选', True)]:
            button = Button(row, text, lambda v=value: self.select_all(v), 'text', width=52, height=36)
            button.pack(side='right')
            self.scope_controls.append(button)
        self.drive_frame = ctk.CTkFrame(self.scope_card, fg_color='transparent')
        self.drive_frame.grid(row=2, column=0, sticky='ew', padx=24, pady=(8, 20))
        for drive in self.engine.fixed_drives():
            value = tk.BooleanVar(value=True)
            button = Button(self.drive_frame, drive, lambda v=value: self.toggle_drive(v),
                            width=92, height=40, corner_radius=12, symbol='check', border_spacing=6)
            button.grid(row=0, column=len(self.drive_buttons), padx=(0, 8), pady=(0, 8))
            self.options.append((drive, value))
            self.drive_buttons.append(button)
            self.scope_controls.append(button)
        if not self.options:
            label(self.drive_frame, '未找到本地固定磁盘，请添加文件夹。', 12, C['muted']).pack(anchor='w')
        tk.Frame.bind(self.drive_frame, '<Configure>', self.layout_drives, add='+')
        ctk.CTkFrame(self.scope_card, height=1, fg_color=C['container']).grid(row=3, column=0, sticky='ew', padx=24)
        row = ctk.CTkFrame(self.scope_card, fg_color='transparent')
        row.grid(row=4, column=0, sticky='ew', padx=24, pady=(16, 8))
        label(row, '指定文件夹', 14, bold=True).pack(side='left')
        add = Button(row, '添加文件夹', self.add_folder, 'text', 'add', width=118, height=40)
        add.pack(side='right')
        self.scope_controls.append(add)
        self.folder_frame = ctk.CTkFrame(self.scope_card, fg_color='transparent')
        self.folder_frame.grid(row=5, column=0, sticky='ew', padx=24, pady=(0, 24))
        self.folder_frame.grid_columnconfigure(0, weight=1)
        self.render_folders()
        label(self.progress_card, '检查进度', 20, bold=True).grid(row=0, column=0, sticky='w', padx=24, pady=(24, 12))
        self.phase = label(self.progress_card, '准备就绪', 12, C['primary'], corner_radius=12,
                           fg_color=C['primary_container'], padx=12, height=28)
        self.phase.grid(row=1, column=0, sticky='w', padx=24)
        self.checked_label = label(self.progress_card, '0', 56, bold=True, height=78)
        self.checked_label.grid(row=2, column=0, sticky='w', padx=24, pady=(16, 0))
        label(self.progress_card, '已检查的演示文件', 12, C['muted']).grid(row=3, column=0, sticky='w', padx=24)
        count_row = ctk.CTkFrame(self.progress_card, fg_color='transparent')
        count_row.grid(row=4, column=0, sticky='ew', padx=24, pady=(20, 20))
        count_row.grid_columnconfigure((0, 1), weight=1)
        self.issue_label = label(count_row, '0', 24, C['error'], bold=True)
        self.issue_label.grid(row=0, column=0, sticky='w')
        self.unchecked_label = label(count_row, '0', 24, C['warning'], bold=True)
        self.unchecked_label.grid(row=0, column=1, sticky='w')
        label(count_row, '编号问题', 12, C['muted']).grid(row=1, column=0, sticky='w')
        label(count_row, '无法检查 / 旧格式', 12, C['muted']).grid(row=1, column=1, sticky='w')
        self.bar = ctk.CTkProgressBar(self.progress_card, height=6, corner_radius=3,
                                    fg_color=C['high'], progress_color=C['primary'])
        self.bar.set(0)
        self.bar.grid(row=5, column=0, sticky='ew', padx=24)
        self.status = tk.StringVar(value='选择检查范围后，点击开始检查。')
        self.status_label = label(self.progress_card, textvariable=self.status, size=12,
                                  color=C['muted'], justify='left', wraplength=290)
        self.status_label.grid(row=6, column=0, sticky='ew', padx=24, pady=(12, 4))
        self.current_path = ElidedLabel(self.progress_card)
        self.current_path.grid(row=7, column=0, sticky='ew', padx=24, pady=(0, 20))
        tk.Frame.bind(self.progress_card, '<Configure>', lambda e: wrap_label(self.status_label,
            e.width / self.progress_card._get_widget_scaling() - 48), add='+')
        hint = ctk.CTkFrame(scroll, fg_color=C['primary_container'], corner_radius=20)
        hint.grid(row=1, column=0, sticky='ew', pady=(20, 0))
        hint.grid_columnconfigure(1, weight=1)
        label(hint, image=icon('info', C['on_primary_container']), width=32).grid(row=0, column=0, rowspan=2, padx=(20, 12), pady=20)
        label(hint, '聚焦批注编号，保留原始文件', 14, C['on_primary_container'], bold=True).grid(row=0, column=1, sticky='w', pady=(16, 2))
        hint_text = label(hint, '包含子文件夹 · 支持 PPTX 等 6 种格式 · 自动生成检查报告', 12,
                          C['on_primary_container'], justify='left')
        hint_text.grid(row=1, column=1, sticky='ew', pady=(0, 16), padx=(0, 16))
        tk.Frame.bind(hint, '<Configure>', lambda e: wrap_label(hint_text, e.width / hint._get_widget_scaling() - 92), add='+')
        footer = ctk.CTkFrame(page, fg_color=C['surface'], corner_radius=0)
        footer.grid(row=1, column=0, sticky='ew', pady=(20, 0))
        footer.grid_columnconfigure(0, weight=1)
        self.selection_label = label(footer, '', 12, C['muted'])
        self.selection_label.grid(row=0, column=0, sticky='w', columnspan=3, pady=(0, 10))
        self.view_results_button = Button(footer, '查看结果', lambda: self.show_page('results'), 'text', 'results', state='disabled')
        self.view_results_button.grid(row=1, column=0, sticky='w')
        self.stop_button = Button(footer, '停止并保存', self.stop, 'outlined', 'stop', state='disabled', width=148)
        self.stop_button.grid(row=1, column=1, padx=12)
        self.start_button = Button(footer, '开始检查', self.start, 'filled', 'play', width=160, height=48, corner_radius=24)
        self.start_button.grid(row=1, column=2)

    def layout_panels(self, event):
        wide = event.width / self.scan_grid._get_widget_scaling() >= 840
        if wide == self.wide:
            return
        self.wide = wide
        self.scan_grid.grid_columnconfigure(0, weight=3, uniform='panels' if wide else '')
        self.scan_grid.grid_columnconfigure(1, weight=2 if wide else 0, uniform='panels' if wide else '')
        self.scope_card.grid(row=0, column=0, sticky='nsew', padx=(0, 16 if wide else 0))
        self.progress_card.grid(row=0 if wide else 1, column=1 if wide else 0, sticky='nsew', pady=(0 if wide else 16, 0))

    def layout_drives(self, event):
        if not self.drive_buttons:
            return
        cell = max(b.winfo_reqwidth() for b in self.drive_buttons) + 8 * self.drive_frame._get_widget_scaling()
        columns = max(1, int(event.width // cell))
        if columns != self.drive_columns:
            self.drive_columns = columns
            for i, button in enumerate(self.drive_buttons):
                button.grid_configure(row=i // columns, column=i % columns)

    def toggle_drive(self, variable):
        variable.set(not variable.get())
        self.update_selection()

    def select_all(self, value):
        for _, variable in self.options:
            variable.set(value)
        self.update_selection()

    def update_selection(self):
        count = sum(var.get() for _, var in self.options)
        for (_, variable), button in zip(self.options, self.drive_buttons):
            active = variable.get()
            button.configure(fg_color=C['primary_container'] if active else C['card'],
                             border_width=0 if active else 1,
                             image=icon('check' if active else 'disk', C['on_primary_container'] if active else C['muted'], 20),
                             text_color=C['on_primary_container'] if active else C['muted'])
            button.normal_border = 0 if active else 1
        self.scope_count.configure(text=f'{count + len(self.folders)} 个位置')
        self.selection_label.configure(text=f'已选 {count} 个磁盘 · {len(self.folders)} 个文件夹    /    包含所有可访问子文件夹')

    def add_folder(self):
        value = filedialog.askdirectory(parent=self.window, title='选择检查文件夹')
        if value and value not in self.folders:
            self.folders.append(value)
            self.render_folders()
            self.update_selection()

    def remove_folder(self, path):
        self.folders.remove(path)
        self.render_folders()
        self.update_selection()

    def render_folders(self):
        for child in self.folder_frame.winfo_children():
            child.destroy()
        self.folder_remove_buttons = []
        if not self.folders:
            empty = label(self.folder_frame, '还没有添加文件夹\n只检查指定资料时，可清空上方磁盘选择。',
                          12, C['muted'], justify='left', height=64)
            empty.grid(row=0, column=0, sticky='ew')
            tk.Frame.bind(empty, '<Configure>', lambda e: wrap_label(empty,
                e.width / self.folder_frame._get_widget_scaling()), add='+')
            return
        for i, path in enumerate(self.folders):
            row = ctk.CTkFrame(self.folder_frame, fg_color=C['low'], corner_radius=12)
            row.grid(row=i, column=0, sticky='ew', pady=(0, 8))
            row.grid_columnconfigure(1, weight=1)
            label(row, image=icon('folder', C['primary'], 20), width=36).grid(row=0, column=0, padx=(8, 0))
            text = ElidedLabel(row)
            text.grid(row=0, column=1, sticky='ew')
            text.set(path)
            button = Button(row, '移除', lambda p=path: self.remove_folder(p), 'text', width=56, height=40)
            button.grid(row=0, column=2, padx=4)
            self.folder_remove_buttons.append(button)

    def _build_results(self):
        page = self.pages['results']
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(2, weight=1)
        top = ctk.CTkFrame(page, fg_color='transparent')
        top.grid(row=0, column=0, sticky='ew', pady=(0, 16))
        self.result_summary = label(top, '完成一次检查后，在这里查看结果。', 12, C['muted'])
        self.result_summary.pack(side='left')
        Button(top, '选择报告', self.choose_report, 'text', 'folder', width=110).pack(side='right')
        self.filters = ctk.CTkFrame(page, fg_color='transparent')
        self.filters.grid(row=1, column=0, sticky='ew', pady=(0, 16))
        self.filters.grid_columnconfigure(0, weight=1)
        chips = ctk.CTkFrame(self.filters, fg_color='transparent')
        chips.grid(row=0, column=0, sticky='w')
        self.filter_buttons = {}
        for i, mode in enumerate(['全部', '编号问题', '未发现问题', '无法检查 / 旧格式']):
            b = Button(chips, mode, lambda m=mode: self.set_filter(m), 'outlined',
                       width=76 if i < 3 else 145, height=36, corner_radius=10)
            b.grid(row=0, column=i, padx=(0, 8))
            self.filter_buttons[mode] = b
        search_row = ctk.CTkFrame(self.filters, fg_color='transparent')
        search_row.grid(row=1, column=0, sticky='ew', pady=(12, 0))
        search_row.grid_columnconfigure(1, weight=1)
        label(search_row, '搜索文件', 12, C['muted']).grid(row=0, column=0, padx=(0, 12))
        self.query = tk.StringVar()
        self.search = ctk.CTkEntry(search_row, textvariable=self.query, height=44, corner_radius=22,
                                  fg_color=C['low'], border_width=1, border_color=C['outline'],
                                  text_color=C['text'], font=(FONT, 14))
        self.search.grid(row=0, column=1, sticky='ew')
        self.query.trace_add('write', lambda *_: self.refresh_results())
        self.result_count = label(search_row, '0 个文件', 12, C['muted'])
        self.result_count.grid(row=0, column=2, padx=(12, 0))
        self.list_card = ctk.CTkFrame(page, fg_color=C['card'], corner_radius=20)
        self.list_card.grid(row=2, column=0, sticky='nsew')
        self.list_card.grid_rowconfigure(0, weight=1)
        self.list_card.grid_columnconfigure(0, weight=1)
        style = ttk.Style(self.window)
        style.theme_use('clam')
        scale = page._get_widget_scaling()
        style.configure('MD3.Treeview', background=C['card'], fieldbackground=C['card'], foreground=C['text'],
                        rowheight=round(44 * scale), borderwidth=0, font=(FONT, -round(14 * scale)), relief='flat')
        style.configure('MD3.Treeview.Heading', background=C['low'], foreground=C['muted'],
                        font=(FONT, -round(14 * scale)), relief='flat', padding=(round(12 * scale), round(12 * scale)))
        style.map('MD3.Treeview', background=[('selected', C['primary_container'])],
                  foreground=[('selected', C['on_primary_container'])])
        style.map('MD3.Treeview.Heading', background=[('active', C['container'])])
        self.tree = ttk.Treeview(self.list_card, columns=('name', 'state', 'duplicates'),
                                 show='headings', selectmode='browse', style='MD3.Treeview', height=4)
        for key, title, width in [('name', '文件名称', 320), ('state', '检查结果', 200), ('duplicates', '重复记录', 90)]:
            self.tree.heading(key, text=title, anchor='w')
            self.tree.column(key, width=round(width * scale), minwidth=round(80 * scale), stretch=key == 'name', anchor='w')
        self.tree.grid(row=0, column=0, sticky='nsew', padx=(12, 0), pady=12)
        style.configure('MD3.Vertical.TScrollbar', background=C['divider'], troughcolor=C['card'],
                        borderwidth=0, arrowsize=round(12 * scale))
        scrollbar = ttk.Scrollbar(self.list_card, command=self.tree.yview,
                                   orient='vertical', style='MD3.Vertical.TScrollbar')
        scrollbar.grid(row=0, column=1, sticky='ns', padx=(0, 8), pady=16)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.tag_configure('problem', foreground=C['error'])
        self.tree.tag_configure('unchecked', foreground=C['warning'])
        self.tree.bind('<<TreeviewSelect>>', self.select_result)
        self.empty = ctk.CTkFrame(self.list_card, fg_color=C['card'])
        self.empty.place(relx=.5, rely=.55, anchor='center')
        label(self.empty, image=icon('scan', C['primary'], 40), anchor='center', height=56).pack()
        self.empty_title = label(self.empty, '检查结果将在这里显示', 18, anchor='center')
        self.empty_title.pack(pady=(8, 4))
        self.empty_note = label(self.empty, '开始一次检查，或选择已保存的报告。', 12, C['muted'], anchor='center')
        self.empty_note.pack()
        details = ctk.CTkFrame(page, fg_color=C['low'], corner_radius=20)
        details.grid(row=3, column=0, sticky='ew', pady=(16, 0))
        details.grid_columnconfigure(0, weight=1)
        self.detail_title = label(details, '文件详情', 14, bold=True)
        self.detail_title.grid(row=0, column=0, sticky='w', padx=20, pady=(12, 4))
        detail_content = ctk.CTkFrame(details, fg_color='transparent')
        detail_content.grid(row=1, column=0, sticky='ew', padx=20, pady=(0, 16))
        detail_content.grid_columnconfigure(0, weight=1)
        self.detail_text = tk.Text(detail_content, height=3, bg=C['low'], fg=C['muted'],
                                  font=(FONT, -round(12 * scale)), wrap='word', borderwidth=0, highlightthickness=0,
                                  relief='flat', selectbackground=C['primary_container'])
        self.detail_text.grid(row=0, column=0, sticky='ew')
        detail_scroll = ttk.Scrollbar(detail_content, command=self.detail_text.yview,
                                      orient='vertical', style='MD3.Vertical.TScrollbar')
        detail_scroll.grid(row=0, column=1, sticky='ns')
        self.detail_text.configure(yscrollcommand=detail_scroll.set)
        self.set_detail('选择一个文件，查看完整路径和检查说明。')
        detail_actions = ctk.CTkFrame(details, fg_color='transparent')
        detail_actions.grid(row=0, column=1, rowspan=2, padx=(8, 16))
        self.location_button = Button(detail_actions, '所在文件夹', self.open_location, 'text', 'folder', state='disabled')
        self.location_button.pack()
        self.copy_button = Button(detail_actions, '复制路径', self.copy_path, 'text', 'copy', state='disabled')
        self.copy_button.pack()
        footer = ctk.CTkFrame(page, fg_color='transparent')
        footer.grid(row=4, column=0, sticky='ew', pady=(16, 0))
        self.report_folder_button = Button(footer, '报告文件夹', self.open_report_folder, 'text', 'folder', state='disabled')
        self.report_folder_button.pack(side='left')
        self.open_button = Button(footer, '打开完整报告', self.open_report, 'filled', 'launch', width=172, state='disabled')
        self.open_button.pack(side='right')
        self.refresh_results()

    def _build_help(self):
        page = self.pages['help']
        page.grid_rowconfigure(0, weight=1)
        page.grid_columnconfigure(0, weight=1)
        viewport, scroll = scroll_area(page)
        viewport.grid(row=0, column=0, sticky='nsew')
        scroll.grid_columnconfigure(0, weight=1)
        sections = [
            ('01', '选择范围，然后开始检查', '默认选择本地固定磁盘。只检查特定资料时，点击“清空”，再添加文件夹。扫描包含子文件夹，窗口缩放不会改变已选范围。'),
            ('02', '从检查结果找到需要处理的文件', '按“编号问题”筛选重复、缺失或非法编号；选择文件可查看详细原因、复制路径或打开所在文件夹。完整报告包含 HTML、CSV、Markdown 和逐文件记录。'),
            ('03', '随时停止，已检查的结果会保存', '点击“停止并保存”会生成部分报告。扫描中关闭窗口会先保存再退出。报告保存在程序旁的“报告”文件夹，每次检查使用独立目录。'),
            ('04', '检查范围与支持格式', '支持 PPTX、PPTM、PPSX、PPSM、POTX、POTM；旧 PPT、PPS、POT 列为未检查。程序只读取源文件，不上传，不修改，也不启动 Office。'),
            ('05', '如何理解检查结论', '本工具检查传统批注作者编号。“未发现问题”指未发现本次编号问题，不代表文件一定能在 PowerPoint 中打开。保存软件标记用于排查线索，不作为问题来源的证明。系统目录、回收站、开发依赖、链接和云端占位项目会跳过；具体原因写入报告。'),
        ]
        for i, (number, title, body) in enumerate(sections):
            card = ctk.CTkFrame(scroll, fg_color=C['card'], corner_radius=20)
            card.grid(row=i, column=0, sticky='ew', pady=(0, 12))
            card.grid_columnconfigure(1, weight=1)
            label(card, number, 14, C['primary'], fg_color=C['primary_container'], corner_radius=12,
                  width=40, height=40, anchor='center').grid(row=0, column=0, rowspan=2, sticky='n', padx=20, pady=20)
            label(card, title, 16, bold=True).grid(row=0, column=1, sticky='w', pady=(20, 8), padx=(0, 20))
            body_label = label(card, body, 14, C['muted'], justify='left', wraplength=620)
            body_label.grid(row=1, column=1, sticky='ew', padx=(0, 24), pady=(0, 20))
            tk.Frame.bind(card, '<Configure>', lambda e, l=body_label: wrap_label(l,
                e.width / l._get_widget_scaling() - 104), add='+')
        label(scroll, '快捷键  Ctrl + Enter 开始检查    Ctrl + F 搜索结果    F1 使用说明', 12, C['muted']).grid(row=6, column=0, sticky='w', padx=8, pady=12)

    def show_page(self, key):
        titles = dict(scan=('PPT 文件检查', '定位批注编号问题，让排查更清晰。'),
                      results=('检查结果', '按问题筛选，快速找到需要处理的文件。'),
                      help=('使用说明', '了解检查范围、结果含义与报告位置。'))
        for name, page in self.pages.items():
            if name == key:
                page.grid(row=1, column=0, sticky='nsew')
            else:
                page.grid_remove()
        self.active_page = key
        self.title.configure(text=titles[key][0])
        self.subtitle.configure(text=titles[key][1])
        for name, (button, caption, symbol) in self.nav.items():
            active = name == key
            color = C['on_primary_container'] if active else C['muted']
            button.configure(fg_color=C['primary_container'] if active else 'transparent', image=icon(symbol, color))
            caption.configure(text_color=color, font=(FONT, 12, 'bold' if active else 'normal'))

    def focus_search(self, _=None):
        self.show_page('results')
        self.search.focus_set()
        return 'break'

    def set_filter(self, mode):
        self.filter_mode = mode
        self.refresh_results()

    def refresh_results(self):
        for mode, button in self.filter_buttons.items():
            selected = mode == self.filter_mode
            button.configure(fg_color=C['primary_container'] if selected else 'transparent',
                             border_width=0 if selected else 1)
            button.normal_border = 0 if selected else 1
        selected = self.tree.selection()
        previous = selected[0] if selected else None
        self.tree.delete(*self.tree.get_children())
        query = self.query.get().casefold().strip()
        statuses = {'编号问题': {'duplicate', 'invalid'}, '未发现问题': {'clear'},
                    '无法检查 / 旧格式': {'uncheckable', 'unsupported'}}.get(self.filter_mode)
        for index, item in enumerate(self.results):
            if (statuses and item['status'] not in statuses) or query not in item['path'].casefold():
                continue
            tag = 'problem' if item['status'] in {'duplicate', 'invalid'} else 'unchecked' if item['status'] != 'clear' else 'clear'
            self.tree.insert('', 'end', iid=str(index), values=(Path(item['path']).name,
                             self.engine.LABELS[item['status']], item['duplicate_records']), tags=(tag,))
        count = len(self.tree.get_children())
        self.result_count.configure(text=f'{count:,} 个文件')
        if previous and self.tree.exists(previous):
            self.tree.selection_set(previous)
        else:
            self.detail_title.configure(text='文件详情')
            self.set_detail('选择一个文件，查看完整路径和检查说明。')
            self.location_button.configure(state='disabled')
            self.copy_button.configure(state='disabled')
        if count:
            self.empty.place_forget()
        else:
            title = '没有匹配的文件' if self.results else '本次未登记演示文件' if self.summary is not None else '检查结果将在这里显示'
            note = '试试其他筛选条件或搜索词。' if self.results else '可查看完整报告，或调整检查范围。' if self.summary is not None else '开始一次检查，或选择已保存的报告。'
            self.empty_title.configure(text=title)
            self.empty_note.configure(text=note)
            self.empty.place(relx=.5, rely=.55, anchor='center')

    def set_detail(self, text):
        self.detail_text.configure(state='normal')
        self.detail_text.delete('1.0', 'end')
        self.detail_text.insert('1.0', text)
        self.detail_text.configure(state='disabled')

    def selected_result(self):
        selected = self.tree.selection()
        return self.results[int(selected[0])] if selected else None

    def select_result(self, _=None):
        item = self.selected_result()
        if item:
            self.detail_title.configure(text='文件详情 · ' + self.engine.LABELS[item['status']])
            self.set_detail(item['path'] + '\n' + (item['note'] or '未发现传统批注作者编号问题。') +
                            (f'\n保存软件：{item["application"]}' if item['application'] else ''))
            self.location_button.configure(state='normal')
            self.copy_button.configure(state='normal', text='复制路径')

    def copy_path(self):
        item = self.selected_result()
        if item:
            self.window.clipboard_clear()
            self.window.clipboard_append(item['path'])
            self.copy_button.configure(text='已复制')

    def open_path(self, path):
        try:
            os.startfile(path)
        except OSError as exc:
            messagebox.showerror('无法打开', str(exc), parent=self.window)

    def open_location(self):
        item = self.selected_result()
        if item:
            self.open_path(Path(item['path']).parent)

    def open_report(self):
        if self.state['report']:
            self.open_path(self.state['report'] / '检查报告.html')

    def open_report_folder(self):
        if self.state['report']:
            self.open_path(self.state['report'])

    def choose_report(self):
        if self.state['running']:
            messagebox.showinfo('检查进行中', '请等待当前检查完成或停止并保存后，再选择报告。', parent=self.window)
            return
        folder = filedialog.askdirectory(parent=self.window, title='选择已保存的报告文件夹',
                                         initialdir=str(self.base_dir / '报告'))
        if folder:
            try:
                self.load_report(Path(folder))
            except (OSError, ValueError, KeyError) as exc:
                messagebox.showerror('无法读取报告', f'请选择包含“扫描摘要.json”和“逐文件详情.jsonl”的报告文件夹。\n{exc}', parent=self.window)

    def load_report(self, report, summary=None):
        summary = summary or json.loads((report / '扫描摘要.json').read_text(encoding='utf-8'))
        results = [json.loads(line) for line in (report / '逐文件详情.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
        self.results, self.summary = results, summary
        self.state['report'] = report
        self.query.set('')
        self.filter_mode = '全部'
        self.refresh_results()
        self.update_counts(summary)
        issues = summary['counts']['duplicate'] + summary['counts']['invalid']
        self.result_summary.configure(text=f'{summary["state"]} · 共 {summary["checked"]:,} 个文件 · 编号问题 {issues:,} 个')
        self.view_results_button.configure(state='normal')
        self.open_button.configure(state='normal' if (report / '检查报告.html').exists() else 'disabled')
        self.report_folder_button.configure(state='normal')

    def update_counts(self, data):
        counts = data['counts']
        self.checked_label.configure(text=f'{data["checked"]:,}')
        self.issue_label.configure(text=f'{counts["duplicate"] + counts["invalid"]:,}')
        self.unchecked_label.configure(text=f'{counts["uncheckable"] + counts["unsupported"]:,}')

    def set_running(self, running):
        self.state['running'] = running
        for control in self.scope_controls + self.folder_remove_buttons:
            control.configure(state='disabled' if running else 'normal')
        self.start_button.configure(state='disabled' if running else 'normal')
        self.stop_button.configure(state='normal' if running else 'disabled')

    def start(self):
        if self.state['running']:
            return
        roots = [path for path, value in self.options if value.get()] + self.folders
        if not roots:
            self.status.set('请选择至少一个磁盘，或添加文件夹。')
            self.phase.configure(text='等待选择范围')
            self.show_page('scan')
            return
        report = self.base_dir / '报告' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        try:
            report.parent.mkdir(exist_ok=True)
        except OSError as exc:
            messagebox.showerror('报告目录无法写入', f'请将程序放到可写目录后重试。\n{exc}', parent=self.window)
            return
        self.state.update(report=report, close_requested=False)
        self.cancelled.clear()
        self.results, self.summary = [], None
        self.query.set('')
        self.refresh_results()
        self.result_summary.configure(text='正在检查，完成后可查看本次结果。')
        for button in (self.view_results_button, self.open_button, self.report_folder_button):
            button.configure(state='disabled')
        self.set_running(True)
        self.update_counts(dict(checked=0, counts={key: 0 for key in self.engine.LABELS}))
        self.phase.configure(text='正在检查', fg_color=C['primary_container'], text_color=C['primary'])
        self.status.set('正在遍历所选目录…')
        self.current_path.set('')
        self.bar.configure(mode='indeterminate')
        self.bar.start()
        self.show_page('scan')
        threading.Thread(target=self.work, args=(roots, report), daemon=True).start()

    def work(self, roots, report):
        try:
            summary = self.engine.scan(roots, report, self.cancelled,
                                       lambda **data: self.messages.put(('progress', data)))
            self.messages.put(('done', summary))
        except Exception as exc:
            self.messages.put(('error', str(exc)))

    def stop(self):
        if self.state['running']:
            self.cancelled.set()
            self.stop_button.configure(state='disabled')
            self.phase.configure(text='正在保存')
            self.status.set('正在停止检查并保存已完成的结果…')

    def poll(self):
        while not self.messages.empty():
            kind, data = self.messages.get_nowait()
            if kind == 'progress':
                self.update_counts(data)
                if not self.cancelled.is_set():
                    self.status.set(f'已遍历 {data["directories"]:,} 个目录 · 跳过 {data["skipped"]:,} 项')
                self.current_path.set(data.get('file', data.get('directory', '')))
                continue
            self.set_running(False)
            self.bar.stop()
            self.bar.configure(mode='determinate')
            if kind == 'done':
                self.bar.set(1)
                if self.state['close_requested']:
                    self.window.destroy()
                    return
                try:
                    self.load_report(self.state['report'], data)
                except (OSError, ValueError, KeyError) as exc:
                    self.phase.configure(text='报告读取失败', fg_color=C['error_container'], text_color=C['error'])
                    self.status.set('报告已保存，可打开报告文件夹查看。')
                    self.report_folder_button.configure(state='normal')
                    messagebox.showerror('报告读取失败', str(exc), parent=self.window)
                else:
                    stopped = data['state'] != '完成'
                    self.phase.configure(text='已停止 · 部分结果' if stopped else '检查完成',
                                         fg_color=C['warning_container'] if stopped else C['success_container'],
                                         text_color=C['warning'] if stopped else C['success'])
                    self.status.set('已保存部分报告。' if stopped else '报告已保存，可查看结果或打开完整报告。')
                self.current_path.set(self.state['report'])
            else:
                self.state['close_requested'] = False
                self.bar.set(0)
                self.phase.configure(text='检查中断', fg_color=C['error_container'], text_color=C['error'])
                self.status.set('已写入的逐文件清单保留在报告目录。')
                self.report_folder_button.configure(state='normal')
                messagebox.showerror('检查中断', data, parent=self.window)
        self.poll_id = self.window.after(100, self.poll)

    def close(self):
        if self.state['running']:
            self.state['close_requested'] = True
            self.stop()
            self.status.set('正在保存部分报告，保存成功后自动关闭。')
        else:
            self.window.after_cancel(self.poll_id)
            self.window.destroy()


def launch_gui(engine, base_dir, window=None):
    if os.name == 'nt':
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Andy.PPTAudit')
    ctk.set_appearance_mode('light')
    window = window or ctk.CTk()
    app = AuditApp(window, engine, base_dir)
    window.audit_app = app
    window.mainloop()
    return app
