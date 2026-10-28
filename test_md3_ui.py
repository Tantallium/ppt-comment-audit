"""验证扫描范围、结果筛选、报告读取和键盘操作。"""
from datetime import datetime
import json
from pathlib import Path
import time
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

import ppt_audit
from md3_ui import AuditApp

HERE = Path(__file__).resolve().parent
RUN = HERE / '2026-10-28-MD3界面' / ('交互验证-' + datetime.now().strftime('%H%M%S'))


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.base = RUN / self._testMethodName
        self.base.mkdir(parents=True)
        self.samples = self.base / '测试文件'
        self.samples.mkdir()
        ns = 'http://schemas.openxmlformats.org/presentationml/2006/main'
        for name, ids in [('项目介绍.pptx', [0, 1, 1]), ('产品说明.pptx', [0, 1])]:
            with zipfile.ZipFile(self.samples / name, 'w') as archive:
                archive.writestr('[Content_Types].xml', '<Types/>')
                archive.writestr('ppt/commentAuthors.xml', f'<p:cmAuthorLst xmlns:p="{ns}">' +
                                 ''.join(f'<p:cmAuthor id="{i}"/>' for i in ids) + '</p:cmAuthorLst>')
        (self.samples / '旧版课件.ppt').write_bytes(b'test legacy')
        (self.samples / '无法读取.pptx').write_bytes(b'test non-zip')
        self.root = tk.Tk()
        self.root.withdraw()
        engine = SimpleNamespace(scan=ppt_audit.scan, fixed_drives=lambda: ['C:\\', 'D:\\'], LABELS=ppt_audit.LABELS)
        self.app = AuditApp(self.root, engine, self.base)
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(str(args[1]))

    def tearDown(self):
        for timer in self.root.tk.call('after', 'info'):
            self.root.after_cancel(timer)
        self.root.destroy()
        self.assertFalse(self.errors)

    def report(self):
        report = self.base / '已保存报告'
        ppt_audit.scan([self.samples], report)
        self.app.load_report(report)
        return report

    def test_scope_add_remove_and_empty_selection(self):
        self.app.select_all(False)
        self.app.start()
        self.assertFalse(self.app.state['running'])
        self.assertIn('至少一个', self.app.status.get())
        with patch('md3_ui.filedialog.askdirectory', return_value=str(self.samples)):
            self.app.add_folder()
            self.app.add_folder()
        self.assertEqual(self.app.folders, [str(self.samples)])
        self.app.remove_folder(str(self.samples))
        self.assertFalse(self.app.folders)
        self.app.drive_buttons[0]._key_invoke(None)
        self.assertTrue(self.app.options[0][1].get())
        self.assertFalse(self.app.options[1][1].get())

    def test_scan_end_to_end_and_source_unchanged(self):
        original = {p.name: p.read_bytes() for p in self.samples.iterdir()}
        self.app.select_all(False)
        self.app.folders.append(str(self.samples))
        self.app.render_folders()
        self.app.start()
        self.assertEqual(self.app.start_button.cget('state'), 'disabled')
        self.assertEqual(self.app.drive_buttons[0].cget('state'), 'disabled')
        limit = time.monotonic() + 10
        while self.app.state['running'] and time.monotonic() < limit:
            self.root.update()
            time.sleep(.02)
        self.assertFalse(self.app.state['running'])
        self.assertEqual(self.app.summary['checked'], 4)
        self.assertEqual(self.app.summary['counts']['duplicate'], 1)
        self.assertEqual(self.app.open_button.cget('state'), 'normal')
        self.assertEqual(self.app.phase.cget('text'), '检查完成')
        self.assertEqual({p.name: p.read_bytes() for p in self.samples.iterdir()}, original)

    def test_filters_search_details_and_report_actions(self):
        report = self.report()
        self.app.show_page('results')
        self.assertEqual(len(self.app.tree.get_children()), 4)
        self.app.set_filter('编号问题')
        self.assertEqual(len(self.app.tree.get_children()), 1)
        self.app.query.set('不匹配')
        self.assertFalse(self.app.tree.get_children())
        self.app.query.set('项目')
        selected = self.app.tree.get_children()[0]
        self.app.tree.selection_set(selected)
        self.app.select_result()
        item = self.app.selected_result()
        self.assertIn('重复', self.app.detail_text.get('1.0', 'end'))
        self.app.copy_path()
        self.assertEqual(self.root.clipboard_get(), item['path'])
        with patch('md3_ui.os.startfile') as opened:
            self.app.open_location()
            self.app.open_report()
            self.app.open_report_folder()
        self.assertEqual([call.args[0] for call in opened.call_args_list],
                         [Path(item['path']).parent, report / '检查报告.html', report])
        self.app.query.set('')
        self.app.set_filter('无法检查 / 旧格式')
        self.assertEqual(len(self.app.tree.get_children()), 2)
        self.app.set_filter('未发现问题')
        self.assertEqual(len(self.app.tree.get_children()), 1)

    def test_keyboard_navigation_and_page_layout(self):
        self.root.deiconify()
        self.root.update()
        self.root.focus_force()
        self.app.start_button.focus_set()
        self.root.update()
        self.assertEqual(self.app.start_button.cget('border_width'), 2)
        self.root.event_generate('<Control-f>')
        self.root.update()
        self.assertEqual(self.app.active_page, 'results')
        self.assertIn('entry', str(self.root.focus_get()))
        for page in ['scan', 'results', 'help']:
            self.app.show_page(page)
            for size in ['820x640', '1180x780']:
                self.root.geometry(size)
                self.root.update()
                frame = self.app.pages[page]
                self.assertLessEqual(frame.winfo_rootx()+frame.winfo_width(),
                                     self.root.winfo_rootx()+self.root.winfo_width())
                self.assertLessEqual(frame.winfo_rooty()+frame.winfo_height(),
                                     self.root.winfo_rooty()+self.root.winfo_height())


if __name__ == '__main__':
    RUN.mkdir(parents=True)
    with (RUN / '测试日志.txt').open('w', encoding='utf-8') as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(InterfaceTests))
    summary = dict(tests=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                   successful=result.wasSuccessful(), output=str(RUN))
    (RUN / '测试结果.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))
    raise SystemExit(0 if result.wasSuccessful() else 1)
