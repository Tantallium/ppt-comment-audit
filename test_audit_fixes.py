"""审计修复回归：两版源码、真实 ZIP/报告及隐藏 Tk 窗口；保留验证记录。"""
import csv
from datetime import datetime
import io
import json
from pathlib import Path
import struct
import sys
import threading
import types
import unittest
from unittest.mock import patch
import zipfile

HERE = Path(__file__).resolve().parent
NS = 'http://schemas.openxmlformats.org/presentationml/2006/main'


def load_source(path, name):
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(path.read_text(encoding='utf-8-sig'), str(path), 'exec'), module.__dict__)
    return module


class AuditFixTests(unittest.TestCase):
    def setUp(self):
        self.folder = self.output / self._testMethodName
        self.folder.mkdir(parents=True, exist_ok=False)

    def package(self, author=None, app=None, custom=None, name='sample.pptx'):
        path = self.folder / name
        if author is None:
            author = f'<p:cmAuthorLst xmlns:p="{NS}"><p:cmAuthor id="1"/><p:cmAuthor id="1"/></p:cmAuthorLst>'
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('[Content_Types].xml', '<Types/>')
            archive.writestr('ppt/commentAuthors.xml', author)
            if app is not None:
                archive.writestr('docProps/app.xml', app)
            if custom is not None:
                archive.writestr('docProps/custom.xml', custom)
        return path

    def test_bad_metadata_preserves_problem_and_reports(self):
        for ids, expected in [('1,1', 'duplicate'), ('-1', 'invalid')]:
            records = ''.join(f'<p:cmAuthor id="{number}"/>' for number in ids.split(','))
            path = self.package(f'<p:cmAuthorLst xmlns:p="{NS}">{records}</p:cmAuthorLst>',
                                app='<Properties><Application>test</Application></Properties>',
                                name=f'{expected}.pptx')
            data = bytearray(path.read_bytes())
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                offset = archive.getinfo('docProps/app.xml').header_offset
            name_len, extra_len = struct.unpack_from('<HH', data, offset + 26)
            data[offset + 30 + name_len + extra_len] = 0xff  # 无效 DEFLATE 块
            path.write_bytes(data)
            before = path.read_bytes()
            result = self.module.inspect_file(path)
            self.assertEqual(result['status'], expected)
            self.assertIn('保存软件元数据无法读取', result['note'])
            report = self.folder / f'report-{expected}'
            summary = self.module.scan([path], report)
            self.assertEqual(summary['counts'][expected], 1)
            self.assertIn('确认编号问题 1 个', (report / '待修复列表.md').read_text(encoding='utf-8'))
            self.assertEqual(path.read_bytes(), before)

    def test_csv_external_text_is_safe_and_json_unchanged(self):
        from xml.sax.saxutils import escape
        values = ['=1+1', '+1+1', '-1+1', '@SUM(1)', '\t=1+1', '\r=1+1',
                  '\n=1+1', '  =1+1', 'WPS 正常', '12.1', '含逗号,引号"']
        for index, value in enumerate(values):
            xml_value = escape(value).replace('\r', '&#13;')
            path = self.package(app=f'<Properties><Application>{xml_value}</Application></Properties>',
                                custom=f'<Properties><property name="KSOProductBuildVer"><value>{xml_value}</value></property></Properties>',
                                name=f'csv-{index}.pptx')
            report = self.folder / f'report-{index}'
            self.module.scan([path], report)
            with (report / '检查清单.csv').open(encoding='utf-8-sig', newline='') as stream:
                row = next(csv.DictReader(stream))
            expected = "'" + value if index < 8 else value
            self.assertEqual(row['保存软件标记'], expected)
            self.assertEqual(row['WPS构建标记'], expected)
            self.assertEqual(row['作者记录数'], '2')
            raw = json.loads((report / '逐文件详情.jsonl').read_text(encoding='utf-8'))
            self.assertEqual(raw['application'], value)
            self.assertEqual(raw['wps_build'], value)

    def test_dtd_rejected_across_encodings(self):
        for encoding in ['utf-8', 'utf-16', 'utf-16-le', 'utf-16-be']:
            declaration = 'UTF-8' if encoding == 'utf-8' else 'UTF-16'
            for external in [False, True]:
                dtd = '<!DOCTYPE p:cmAuthorLst SYSTEM "file:///nonexistent-audit.dtd">' if external else '<!DOCTYPE p:cmAuthorLst [<!ENTITY sample "1">]>'
                value = '1' if external else '&sample;'
                xml = f'<?xml version="1.0" encoding="{declaration}"?>{dtd}<p:cmAuthorLst xmlns:p="{NS}"><p:cmAuthor id="{value}"/></p:cmAuthorLst>'
                path = self.package(xml.encode(encoding), name=f'{encoding}-{external}.pptx')
                result = self.module.inspect_file(path)
                self.assertEqual(result['status'], 'uncheckable')
                self.assertIn('DTD', result['note'])

    def test_normal_xml_encodings_and_doctype_comment(self):
        for encoding in ['utf-8', 'utf-16', 'utf-16-le', 'utf-16-be']:
            declaration = 'UTF-8' if encoding == 'utf-8' else 'UTF-16'
            xml = f'<?xml version="1.0" encoding="{declaration}"?><p:cmAuthorLst xmlns:p="{NS}"><!-- <!DOCTYPE is only comment text -->甲<p:cmAuthor id="1"/></p:cmAuthorLst>'
            path = self.package(xml.encode(encoding), name=f'{encoding}.pptx')
            self.assertEqual(self.module.inspect_file(path)['status'], 'clear')

    def gui_case(self, action, fail=False):
        import tkinter as tk
        import customtkinter as ctk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        destroy = root.destroy

        def destroy_test_window():
            # 同一测试进程连续创建 Tk，避免上一窗口的计时器进入下一用例。
            for callback in root.tk.call('after', 'info'):
                root.after_cancel(callback)
            destroy()

        root.destroy = destroy_test_window
        entered = threading.Event()
        finished = threading.Event()
        errors = []
        observation = {}
        original_scan = self.module.scan
        report = self.folder / 'gui-report'
        sample = self.package()

        def worker(roots, output, cancelled, notify):
            try:
                entered.set()
                if not cancelled.wait(5):
                    raise AssertionError('未收到停止事件')
                if fail:
                    raise OSError('模拟报告写入失败')
                observation['report'] = str(output)
                return original_scan([sample], output, cancelled, notify)
            finally:
                finished.set()

        def button(text):
            app = root.audit_app
            return {'开始检查': app.start_button, '停止并保存结果': app.stop_button}[text]

        def after_started():
            if not entered.is_set():
                root.after(20, after_started)
                return
            if action == 'close':
                root.tk.call(root.protocol('WM_DELETE_WINDOW'))
            else:
                button('停止并保存结果').invoke()
            if fail or action == 'stop':
                root.after(50, check_stays_open)

        def check_stays_open():
            ready = bool(errors) if fail else str(button('开始检查').cget('state')) == 'normal'
            if not ready:
                root.after(50, check_stays_open)
                return
            observation['stayed_open'] = bool(root.winfo_exists())
            root.tk.call(root.protocol('WM_DELETE_WINDOW'))

        def start():
            root.audit_app.base_dir = self.folder
            button('开始检查').invoke()
            root.after(20, after_started)

        def timeout():
            observation['timed_out'] = True
            root.destroy()

        timer = root.after(8000, timeout)
        root.after(0, start)
        try:
            with patch.object(self.module, 'fixed_drives', return_value=[str(self.folder)]), \
                 patch.object(self.module, 'scan', side_effect=worker), \
                 patch.object(messagebox, 'showerror', side_effect=lambda *args, **kwargs: errors.append(args)):
                self.module.launch_gui(root)
        finally:
            try:
                root.after_cancel(timer)
                if root.winfo_exists():
                    root.destroy()
            except tk.TclError:
                pass
        self.assertTrue(finished.wait(1))
        self.assertNotIn('timed_out', observation)
        if fail:
            self.assertEqual(len(errors), 1)
            self.assertIn('模拟报告写入失败', errors[0][1])
            self.assertTrue(observation['stayed_open'])
        else:
            self.assertFalse(errors)
            report = Path(observation['report'])
            summary = json.loads((report / '扫描摘要.json').read_text(encoding='utf-8'))
            self.assertIn('已停止', summary['state'])
            self.assertTrue((report / '检查报告.html').exists())
            self.assertTrue((report / '待修复列表.md').exists())
            if action == 'stop':
                self.assertTrue(observation['stayed_open'])

    def test_gui_close_saves_then_exits(self):
        self.gui_case('close')

    def test_gui_close_error_keeps_window(self):
        self.gui_case('close', fail=True)

    def test_gui_stop_keeps_window(self):
        self.gui_case('stop')


if __name__ == '__main__':
    run = HERE / '验证记录' / ('审计修复回归-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    run.mkdir(parents=True, exist_ok=False)
    all_ok = True
    records = []
    with (run / '测试日志.txt').open('w', encoding='utf-8') as log:
        for label, source in [('脚本版', HERE / 'ppt_audit.py'),
                              ('便携版源码', HERE / '便携版打包/源码/ppt_audit.py')]:
            module = load_source(source, 'ppt_audit')
            AuditFixTests.module = module
            AuditFixTests.output = run / label / '新增回归'
            with patch.dict(sys.modules, {'ppt_audit': module}):
                original = load_source(HERE / 'test_ppt_audit.py', 'existing_tests')
            original.RUN = run / label / '原有回归'
            original.FIXTURES = original.RUN / '合成样本'
            suite = unittest.TestSuite([
                unittest.defaultTestLoader.loadTestsFromTestCase(AuditFixTests),
                unittest.defaultTestLoader.loadTestsFromModule(original),
            ])
            log.write(f'\n{label}\n')
            result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
            records.append(dict(version=label, tests=result.testsRun,
                                failures=len(result.failures), errors=len(result.errors),
                                successful=result.wasSuccessful()))
            all_ok &= result.wasSuccessful()
    (run / '测试结果.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(output=str(run), results=records), ensure_ascii=False, indent=2))
    sys.exit(0 if all_ok else 1)
