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

from scan_paths import MODES, path_key


VERSION = '1.7'
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
              warning='\ue002', document='\ue24d', repair='\ue869')


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
        kwargs.setdefault('width', 1)
        kwargs.setdefault('height', 28)
        super().__init__(parent, text='', anchor='w', font=(FONT, 12),
                         text_color=C['muted'], **kwargs)
        self.grid_propagate(False)
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
        self.state = dict(running=False, repairing=False, report=None, close_requested=False)
        self.repair_cancelled = threading.Event()
        self.repair_info, self.repair_directory = {}, None
        self.repair_mode = tk.StringVar(value='另存修复版')
        self.active_repair_in_place = False
        self.options, self.drive_buttons, self.folders, self.scope_controls = [], [], [], []
        self.scan_mode, self.exclude_dirs = 'recommended', []
        self.scan_settings_path = self.base_dir / '扫描设置.json'
        self.scan_settings_error = ''
        try:
            settings = json.loads(self.scan_settings_path.read_text(encoding='utf-8'))
            if (not isinstance(settings, dict) or settings.get('mode') not in MODES
                    or not isinstance(settings.get('exclude_dirs'), list)
                    or any(not isinstance(path, str) or not path.strip() for path in settings['exclude_dirs'])):
                raise ValueError('扫描设置内容不完整')
            self.scan_mode = settings['mode']
            self.exclude_dirs = list(dict.fromkeys(path_key(path) for path in settings['exclude_dirs']))
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            self.scan_settings_error = f'上次设置未读取，当前使用默认设置：{exc}'
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
        label(badge, '本地处理', 12, C['success'], image=icon('shield', C['success'], 16),
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
        mode_row = ctk.CTkFrame(self.scope_card, fg_color='transparent')
        mode_row.grid(row=1, column=0, sticky='ew', padx=24)
        mode_row.grid_columnconfigure((0, 1), weight=1)
        self.scan_mode_buttons = {}
        for column, (mode, caption) in enumerate(MODES.items()):
            button = Button(mode_row, caption, lambda m=mode: self.set_scan_mode(m),
                            'outlined', width=120, height=40)
            button.grid(row=0, column=column, sticky='ew', padx=(0, 8) if column == 0 else (0, 0))
            self.scan_mode_buttons[mode] = button
            self.scope_controls.append(button)
        self.scan_mode_note = label(self.scope_card, '', 12, C['muted'], justify='left', wraplength=280)
        self.scan_mode_note.grid(row=2, column=0, sticky='ew', padx=24, pady=(8, 16))
        self.update_scan_mode()
        row = ctk.CTkFrame(self.scope_card, fg_color='transparent')
        row.grid(row=3, column=0, sticky='ew', padx=24)
        label(row, '本地磁盘', 14, bold=True).pack(side='left')
        for text, value in [('清空', False), ('全选', True)]:
            button = Button(row, text, lambda v=value: self.select_all(v), 'text', width=52, height=36)
            button.pack(side='right')
            self.scope_controls.append(button)
        self.drive_frame = ctk.CTkFrame(self.scope_card, fg_color='transparent')
        self.drive_frame.grid(row=4, column=0, sticky='ew', padx=24, pady=(8, 20))
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
        ctk.CTkFrame(self.scope_card, height=1, fg_color=C['container']).grid(row=5, column=0, sticky='ew', padx=24)
        row = ctk.CTkFrame(self.scope_card, fg_color='transparent')
        row.grid(row=6, column=0, sticky='ew', padx=24, pady=(16, 8))
        label(row, '指定文件夹', 14, bold=True).pack(side='left')
        add = Button(row, '添加文件夹', self.add_folder, 'text', 'add', width=118, height=40)
        add.pack(side='right')
        self.scope_controls.append(add)
        self.folder_frame = ctk.CTkFrame(self.scope_card, fg_color='transparent')
        self.folder_frame.grid(row=7, column=0, sticky='ew', padx=24, pady=(0, 8))
        self.folder_frame.grid_columnconfigure(0, weight=1)
        self.render_folders()
        self.exclusions_button = Button(self.scope_card, '', self.toggle_exclusions,
                                        'text', height=40, anchor='w')
        self.exclusions_button.grid(row=8, column=0, sticky='ew', padx=24, pady=(0, 16))
        self.scope_controls.append(self.exclusions_button)
        self.exclusions_open = False
        self.exclusions_panel = ctk.CTkFrame(self.scope_card, fg_color='transparent')
        self.exclusions_panel.grid_columnconfigure(0, weight=1)
        note = label(self.exclusions_panel, '两种模式均生效，设置自动保存。', 12, C['muted'], justify='left')
        note.grid(row=0, column=0, sticky='w', pady=(0, 8))
        add_exclusion = Button(self.exclusions_panel, '添加不扫描文件夹', self.add_exclusion,
                               'outlined', 'add', height=40, width=180)
        add_exclusion.grid(row=1, column=0, sticky='w', pady=(0, 12))
        self.scope_controls.append(add_exclusion)
        self.exclusion_list = ctk.CTkFrame(self.exclusions_panel, fg_color='transparent')
        self.exclusion_list.grid(row=2, column=0, sticky='ew')
        self.exclusion_list.grid_columnconfigure(0, weight=1)
        self.render_exclusions()
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
        self.selection_label.configure(text=f'{MODES[self.scan_mode]} · 已选 {count} 个磁盘 · {len(self.folders)} 个文件夹')

    def update_scan_mode(self):
        for mode, button in self.scan_mode_buttons.items():
            active = mode == self.scan_mode
            button.configure(fg_color=C['primary_container'] if active else C['card'],
                             border_width=0 if active else 1,
                             text_color=C['on_primary_container'] if active else C['muted'])
            button.normal_border = 0 if active else 1
        note = ('跳过已识别的程序、游戏库与缓存。\n手动指定这些目录仍可检查。'
                if self.scan_mode == 'recommended' else
                '保留基础排除，检查程序与缓存目录。\n自定义排除仍生效。')
        self.scan_mode_note.configure(text=self.scan_settings_error or note,
                                      text_color=C['warning'] if self.scan_settings_error else C['muted'])

    def save_scan_settings(self):
        try:
            self.scan_settings_path.write_text(json.dumps(
                dict(mode=self.scan_mode, exclude_dirs=self.exclude_dirs), ensure_ascii=False, indent=2),
                encoding='utf-8')
            self.scan_settings_error = ''
        except OSError as exc:
            self.scan_settings_error = f'本次设置已生效，重启后无法保留：{exc}'
        self.update_scan_mode()

    def set_scan_mode(self, mode):
        if self.state['running']:
            return
        self.scan_mode = mode
        self.save_scan_settings()
        self.update_selection()

    def toggle_exclusions(self):
        self.exclusions_open = not self.exclusions_open
        if self.exclusions_open:
            self.exclusions_panel.grid(row=9, column=0, sticky='ew', padx=24, pady=(0, 20))
        else:
            self.exclusions_panel.grid_remove()
        self.render_exclusions()

    def add_exclusion(self):
        value = filedialog.askdirectory(parent=self.window, title='选择不扫描的文件夹')
        if value:
            value = path_key(value)
            if value not in self.exclude_dirs:
                self.exclude_dirs.append(value)
                self.save_scan_settings()
                self.render_exclusions()

    def remove_exclusion(self, path):
        self.exclude_dirs.remove(path)
        self.save_scan_settings()
        self.render_exclusions()

    def render_exclusions(self):
        self.exclusions_button.configure(text=f'{"收起" if self.exclusions_open else "展开"}不扫描文件夹 · {len(self.exclude_dirs)}')
        for child in self.exclusion_list.winfo_children():
            child.destroy()
        self.exclusion_remove_buttons = []
        for i, path in enumerate(self.exclude_dirs):
            row = ctk.CTkFrame(self.exclusion_list, fg_color=C['low'], corner_radius=12)
            row.grid(row=i, column=0, sticky='ew', pady=(0, 8))
            row.grid_columnconfigure(0, weight=1)
            text = ElidedLabel(row)
            text.grid(row=0, column=0, sticky='ew', padx=(12, 0))
            text.set(path)
            button = Button(row, '移除', lambda p=path: self.remove_exclusion(p), 'text', width=56, height=40)
            button.grid(row=0, column=1, padx=4)
            self.exclusion_remove_buttons.append(button)

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
        self.result_summary = label(top, '完成一次检查后，在这里查看结果。', 12, C['muted'], wraplength=320, justify='left')
        self.result_summary.pack(side='left')
        Button(top, '选择报告', self.choose_report, 'text', 'folder', width=110).pack(side='right')
        self.repair_folder_button = Button(top, '修复文件夹', self.open_repair_folder, 'text', 'folder', width=120, state='disabled')
        self.repair_folder_button.pack(side='right', padx=(0, 8))
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
        mode_row = ctk.CTkFrame(self.filters, fg_color='transparent')
        mode_row.grid(row=0, column=1, sticky='e', padx=(12, 0))
        label(mode_row, '修复方式', 12, C['muted']).pack(side='left', padx=(0, 8))
        self.window.option_add('*TCombobox*Listbox.font', (FONT, -round(14 * page._get_widget_scaling())))
        self.repair_mode_combo = ttk.Combobox(mode_row, textvariable=self.repair_mode, state='readonly',
                                             values=['另存修复版', '直接修复原文件'], width=17,
                                             font=(FONT, -round(14 * page._get_widget_scaling())), style='MD3.TCombobox')
        self.repair_mode_combo.pack(side='left')
        search_row = ctk.CTkFrame(self.filters, fg_color='transparent')
        search_row.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(12, 0))
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
        style.configure('MD3.TCombobox', padding=(round(8 * scale), round(10 * scale)),
                        fieldbackground=C['low'], background=C['low'], foreground=C['text'],
                        arrowcolor=C['primary'], bordercolor=C['outline'])
        style.map('MD3.TCombobox', fieldbackground=[('readonly', C['low'])],
                  foreground=[('disabled', C['muted']), ('readonly', C['text'])],
                  selectbackground=[('readonly', C['low'])], selectforeground=[('readonly', C['text'])],
                  bordercolor=[('focus', C['primary'])])
        style.configure('MD3.Treeview', background=C['card'], fieldbackground=C['card'], foreground=C['text'],
                        rowheight=round(44 * scale), borderwidth=0, font=(FONT, -round(14 * scale)), relief='flat')
        style.configure('MD3.Treeview.Heading', background=C['low'], foreground=C['muted'],
                        font=(FONT, -round(14 * scale)), relief='flat', padding=(round(12 * scale), round(12 * scale)))
        style.map('MD3.Treeview', background=[('selected', C['primary_container'])],
                  foreground=[('selected', C['on_primary_container'])])
        style.map('MD3.Treeview.Heading', background=[('active', C['container'])])
        self.tree = ttk.Treeview(self.list_card, columns=('name', 'state', 'repair'),
                                 show='headings', selectmode='extended', style='MD3.Treeview', height=4)
        for key, title, width in [('name', '文件名称', 320), ('state', '原文件检查结果', 190), ('repair', '修复状态', 140)]:
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
        self.report_folder_button = Button(footer, '报告文件夹', self.open_report_folder, 'text', 'folder', width=110, state='disabled')
        self.report_folder_button.pack(side='left')
        self.repair_selected_button = Button(footer, '修复选中', lambda: self.begin_repair(True),
                                              'tonal', 'repair', width=132, state='disabled')
        self.repair_selected_button.pack(side='left', padx=(8, 0))
        self.repair_action_host = ctk.CTkFrame(footer, fg_color='transparent')
        self.repair_action_host.pack(side='left', padx=8)
        self.repair_all_button = Button(self.repair_action_host, '修复全部问题', lambda: self.begin_repair(False),
                                         'tonal', width=142, state='disabled')
        self.repair_all_button.grid(row=0, column=0)
        self.repair_stop_button = Button(self.repair_action_host, '停止修复', self.stop_repair,
                                          'outlined', 'stop', width=142)
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
            ('01', '选择范围，然后开始检查', '默认推荐扫描，跳过已识别的程序、游戏库与缓存；全面扫描保留基础排除。手动指定自动排除的目录仍可检查。“不扫描文件夹”在两种模式下都生效，模式和排除列表自动保存。只检查特定资料时，点击“清空”，再添加文件夹。'),
            ('02', '选择修复方式', '默认“另存修复版”，也可选“直接修复原文件”。原位模式先备份，再复查并写回，保持原文件名和路径。选中问题文件后点击“修复选中”，或点击“修复全部问题”；Ctrl 或 Shift 可多选。'),
            ('03', '随时停止，已检查的结果会保存', '点击“停止并保存”会生成部分报告。扫描中关闭窗口会先保存再退出。报告保存在程序旁的“报告”文件夹，每次检查使用独立目录。'),
            ('04', '备份与支持格式', '原位修复的备份保存在记录目录内的“PPT编号修复备份”，该目录会被扫描跳过。点击“修复文件夹”可查看备份和记录。支持 PPTX、PPTM、PPSX、PPSM、POTX、POTM；旧格式单独列为未检查。'),
            ('05', '如何理解修复结果', '自动修复重复、缺失、非法或超范围的传统批注作者编号。可明确对应的批注引用同步更新；作者归属不明时标为“需人工确认”。原位修复成功后列表更新为复查结果，扫描时的报告保持原记录。'),
            ('06', '检查结论的范围', '本工具处理传统批注作者编号；编号检查通过不代表文件没有其他打开问题。保存软件标记用于排查线索，不作为问题来源的证明。系统目录、回收站、开发依赖、链接和云端占位项目会跳过，具体原因写入报告。'),
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
        label(scroll, '快捷键  Ctrl + Enter 开始检查    Ctrl + F 搜索结果    F1 使用说明', 12, C['muted']).grid(row=7, column=0, sticky='w', padx=8, pady=12)

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
        previous = selected
        self.tree.delete(*self.tree.get_children())
        query = self.query.get().casefold().strip()
        statuses = {'编号问题': {'duplicate', 'invalid'}, '未发现问题': {'clear'},
                    '无法检查 / 旧格式': {'uncheckable', 'unsupported'}}.get(self.filter_mode)
        for index, item in enumerate(self.results):
            if (statuses and item['status'] not in statuses) or query not in item['path'].casefold():
                continue
            tag = 'problem' if item['status'] in {'duplicate', 'invalid'} else 'unchecked' if item['status'] != 'clear' else 'clear'
            repaired = self.repair_info.get(item['path'])
            fixed_text = '已原位修复' if repaired and repaired.get('mode') == 'in_place' else '已另存修复版'
            repair_text = {'fixed': fixed_text, 'unchanged': '无需修复', 'needs_review': '需人工确认',
                           'failed': '修复失败'}.get(repaired['status']) if repaired else '待修复' if tag == 'problem' else '—'
            self.tree.insert('', 'end', iid=str(index), values=(Path(item['path']).name,
                             self.engine.LABELS[item['status']], repair_text), tags=(tag,))
        count = len(self.tree.get_children())
        self.result_count.configure(text=f'{count:,} 个文件')
        retained = [item for item in previous if self.tree.exists(item)]
        if retained:
            self.tree.selection_set(*retained)
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
        self.update_repair_actions()

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
            repair = self.repair_info.get(item['path'])
            self.set_detail(item['path'] + '\n' + (item['note'] or '未发现传统批注作者编号问题。') +
                            (f'\n保存软件：{item["application"]}' if item['application'] else '') +
                            (f'\n{repair["note"]}\n修复后文件：{repair["output"]}' if repair else '') +
                            (f'\n原文件备份：{repair["backup"]}' if repair and repair.get('backup') else ''))
            self.location_button.configure(state='normal')
            self.copy_button.configure(state='normal', text='复制路径')
        self.update_repair_actions()

    def repair_paths(self, selected_only):
        items = [self.results[int(i)] for i in self.tree.selection()] if selected_only else self.results
        return [item['path'] for item in items if item['status'] in {'duplicate', 'invalid'}]

    def update_repair_actions(self):
        busy = self.state['running'] or self.state['repairing']
        self.repair_mode_combo.configure(state='disabled' if busy else 'readonly')
        self.repair_selected_button.configure(state='normal' if not busy and self.repair_paths(True) else 'disabled')
        self.repair_all_button.configure(state='normal' if not busy and self.repair_paths(False) else 'disabled')

    def open_repair_folder(self):
        if self.repair_directory:
            self.open_path(self.repair_directory)

    def begin_repair(self, selected_only):
        if self.state['running'] or self.state['repairing']:
            return
        paths = self.repair_paths(selected_only)
        if not paths:
            return
        in_place = self.repair_mode.get() == '直接修复原文件'
        title = f'选择 {len(paths)} 个文件的备份和记录位置（修复将写回原文件）' if in_place else f'选择 {len(paths)} 个文件的修复输出位置（保留原文件）'
        parent = filedialog.askdirectory(parent=self.window, title=title,
                                         initialdir=str(self.base_dir))
        if not parent:
            return
        self.active_repair_in_place = in_place
        prefix = 'PPT原位修复_' if in_place else 'PPT编号修复_'
        self.repair_directory = Path(parent) / (prefix + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        self.state.update(repairing=True, close_requested=False)
        self.repair_cancelled.clear()
        self.update_repair_actions()
        self.start_button.configure(state='disabled')
        self.repair_folder_button.configure(state='disabled')
        self.repair_all_button.grid_remove()
        self.repair_stop_button.configure(state='normal')
        self.repair_stop_button.grid(row=0, column=0)
        action = '备份并原位修复' if in_place else '另存修复版'
        self.result_summary.configure(text=f'正在{action} · 0 / {len(paths)}')
        threading.Thread(target=self.repair_work, args=(paths, self.repair_directory, in_place), daemon=True).start()

    def repair_work(self, paths, output, in_place=False):
        try:
            from ppt_repair import repair_batch
            result = repair_batch(paths, output, self.repair_cancelled,
                                   lambda **data: self.messages.put(('repair_progress', data)), in_place=in_place)
            self.messages.put(('repair_done', result))
        except Exception as exc:
            self.messages.put(('repair_error', str(exc)))

    def stop_repair(self):
        self.repair_cancelled.set()
        self.repair_stop_button.configure(state='disabled')
        self.result_summary.configure(text='正在完成当前文件，随后保存修复记录。')

    def handle_repair_message(self, kind, data):
        if kind == 'repair_progress':
            self.repair_info[data['record']['source']] = data['record']
            record = data['record']
            if record.get('mode') == 'in_place' and record.get('after'):
                self.results = [record['after'] if item['path'] == record['source'] else item for item in self.results]
                if self.summary:
                    self.summary['counts'] = {key: sum(item['status'] == key for item in self.results) for key in self.engine.LABELS}
                    self.update_counts(self.summary)
                self.open_button.configure(text='扫描时报告')
            self.refresh_results()
            if not self.repair_cancelled.is_set():
                action = '已写回' if self.active_repair_in_place else '已另存'
                self.result_summary.configure(text=f'修复 {data["done"]} / {data["total"]} · {action} {data["counts"]["fixed"]} 个')
            self.select_result()
            return False
        self.state['repairing'] = False
        self.start_button.configure(state='normal')
        self.repair_stop_button.grid_remove()
        self.repair_all_button.grid(row=0, column=0)
        self.repair_folder_button.configure(state='normal' if self.repair_directory.exists() else 'disabled')
        self.update_repair_actions()
        if kind == 'repair_done':
            counts = data['counts']
            self.result_summary.configure(text=f'{data["state"]} · 修复 {counts["fixed"]} · 需确认 {counts["needs_review"]} · 失败 {counts["failed"]}')
            if self.state['close_requested']:
                self.window.destroy()
                return True
        else:
            self.state['close_requested'] = False
            self.result_summary.configure(text='修复中断 · 已完成文件与备份保留')
            messagebox.showerror('修复中断', data, parent=self.window)
        return False

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
        if self.state['running'] or self.state['repairing']:
            messagebox.showinfo('任务进行中', '请等待当前检查或修复完成后，再选择报告。', parent=self.window)
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
        self.repair_info, self.repair_directory = {}, None
        self.repair_folder_button.configure(state='disabled')
        self.open_button.configure(text='打开完整报告')
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
        for control in self.scope_controls + self.folder_remove_buttons + self.exclusion_remove_buttons:
            control.configure(state='disabled' if running else 'normal')
        self.start_button.configure(state='disabled' if running else 'normal')
        self.stop_button.configure(state='normal' if running else 'disabled')
        self.update_repair_actions()

    def start(self):
        if self.state['running'] or self.state['repairing']:
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
        self.repair_info, self.repair_directory = {}, None
        self.repair_folder_button.configure(state='disabled')
        self.open_button.configure(text='打开完整报告')
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
        options = dict(mode=self.scan_mode, exclude_dirs=list(self.exclude_dirs), explicit_roots=list(self.folders))
        threading.Thread(target=self.work, args=(roots, report, options), daemon=True).start()

    def work(self, roots, report, options):
        try:
            summary = self.engine.scan(roots, report, self.cancelled,
                                       lambda **data: self.messages.put(('progress', data)), **options)
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
            if kind.startswith('repair_'):
                if self.handle_repair_message(kind, data):
                    return
                continue
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
        if self.state['repairing']:
            self.state['close_requested'] = True
            self.stop_repair()
            self.result_summary.configure(text='正在完成当前文件，保存修复记录后关闭。')
        elif self.state['running']:
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
