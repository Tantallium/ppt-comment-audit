"""扫描模式、排除边界、设置保存与两种入口的一致性验证。"""
from datetime import datetime
import json
import os
from pathlib import Path
import threading
import time
import types
import unittest
from unittest.mock import patch
import zipfile

import ppt_audit
from scan_paths import discover_files, path_key


HERE = Path(__file__).resolve().parent
RUN = HERE / '验证记录' / ('扫描优化-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))


def fixture(path, ids=(1, 1)):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        archive.writestr('ppt/commentAuthors.xml',
            '<p:cmAuthorLst xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
            + ''.join(f'<p:cmAuthor id="{number}"/>' for number in ids) + '</p:cmAuthorLst>')
    return path


def load_portable():
    path = HERE / '便携版打包/源码/ppt_audit.py'
    module = types.ModuleType('portable_scan_test')
    module.__file__ = str(path)
    exec(compile(path.read_text(encoding='utf-8-sig'), str(path), 'exec'), module.__dict__)
    return module


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.folder = RUN / self._testMethodName
        self.folder.mkdir(parents=True)
        self.data = self.folder / 'data'
        self.files = {name: fixture(self.data / name) for name in (
            '资料/工作.pptx', 'AppData/Local/Claude/outputs/BP.pptx',
            '03_软件与安装包/backup/QQfile_recv/讲义.pptx', '05_游戏/课程.pptx',
            '安装目录/site-packages/pptx/templates/default.pptx',
            'SteamLibrary/steamapps/common/game/example.pptx',
            '普通资料/SteamLibrary/收藏.pptx', '.git/内部.pptx',
            'PPT编号修复备份/备份.pptx', '不扫描/旧.pptx', '不扫描-保留/新.pptx')}

    def discover(self, roots=None, **options):
        skipped, visited = [], []
        found = list(discover_files(roots or [self.data], lambda p, r: skipped.append((str(p), r)),
                                   threading.Event(), lambda **info: visited.append(info['directory']),
                                   (), **options))
        return set(found), skipped, visited

    def test_recommended_prunes_programs_and_preserves_mixed_documents(self):
        found, skipped, visited = self.discover()
        excluded = {'安装目录/site-packages/pptx/templates/default.pptx',
                    'SteamLibrary/steamapps/common/game/example.pptx',
                    '.git/内部.pptx', 'PPT编号修复备份/备份.pptx'}
        self.assertEqual(found, {path for name, path in self.files.items() if name not in excluded})
        self.assertNotIn(str(self.data / 'SteamLibrary'), visited)
        self.assertNotIn(str(self.data / '安装目录/site-packages'), visited)
        self.assertTrue(any(reason == '推荐排除：Steam 游戏库' for _, reason in skipped))

    def test_full_mode_retains_basic_exclusions(self):
        found, _, _ = self.discover(mode='full')
        self.assertEqual(found, {path for name, path in self.files.items()
                                 if name not in {'.git/内部.pptx', 'PPT编号修复备份/备份.pptx'}})

    def test_custom_exclusion_is_path_bounded_and_applies_to_both_modes(self):
        excluded = self.data / '不扫描'
        for mode in ('full', 'recommended'):
            found, skipped, _ = self.discover(mode=mode, exclude_dirs=[str(excluded).upper()],
                                             explicit_roots=[excluded])
            self.assertNotIn(self.files['不扫描/旧.pptx'], found)
            self.assertIn(self.files['不扫描-保留/新.pptx'], found)
            self.assertTrue(any(reason == '自定义排除目录' for _, reason in skipped))
            found, _, _ = self.discover([excluded / '旧.pptx'], mode=mode,
                                       exclude_dirs=[excluded], explicit_roots=[excluded / '旧.pptx'])
            self.assertFalse(found)

    def test_explicit_root_overrides_recommendation_with_overlap_and_no_duplicates(self):
        selected = self.data / '安装目录/site-packages'
        nested = selected / 'pptx'
        for roots in ([self.data, selected], [selected, self.data], [self.data, nested]):
            found, _, _ = self.discover(roots, explicit_roots=[roots[1] if roots[0] == self.data else selected])
            self.assertIn(self.files['安装目录/site-packages/pptx/templates/default.pptx'], found)
            self.assertNotIn(self.files['SteamLibrary/steamapps/common/game/example.pptx'], found)
        visited = list(discover_files([self.data, selected], lambda *_: None,
                       threading.Event(), lambda **_: None, (), explicit_roots=[selected]))
        self.assertEqual(len(visited), len(set(visited)))

    def test_known_cache_paths_are_exact_and_explicitly_selectable(self):
        local = self.data / 'AppData/Local'
        cached = fixture(local / 'uv/cache/template.pptx')
        program = fixture(local / 'Programs/Demo/template.pptx')
        with patch.dict(os.environ, {'LOCALAPPDATA': str(local)}):
            found, _, _ = self.discover()
            self.assertNotIn(cached, found)
            self.assertNotIn(program, found)
            self.assertIn(self.files['AppData/Local/Claude/outputs/BP.pptx'], found)
            found, _, _ = self.discover([self.data, program.parent], explicit_roots=[program.parent])
            self.assertIn(program, found)

    def test_cloud_and_reparse_attributes_skip_without_traversal(self):
        for attributes in (0x1000, 0x40000, 0x400000, 0x400):
            info = types.SimpleNamespace(st_mode=0o040755, st_file_attributes=attributes)
            with patch('scan_paths.os.lstat', return_value=info), patch('scan_paths.os.scandir') as opened:
                found, skipped, _ = self.discover()
                self.assertFalse(found)
                self.assertEqual(len(skipped), 1)
                opened.assert_not_called()

    def test_report_mode_exclusions_and_entrypoint_parity(self):
        results = []
        before = {name: path.read_bytes() for name, path in self.files.items()}
        for label, engine in [('source', ppt_audit), ('portable', load_portable())]:
            report = self.folder / label
            summary = engine.scan([self.data], report, exclude_dirs=[self.data / '不扫描'])
            details = [json.loads(line) for line in (report / '逐文件详情.jsonl').read_text(encoding='utf-8').splitlines()]
            results.append(sorted(details, key=lambda item: item['path']))
            self.assertEqual(summary['scan_mode'], 'recommended')
            self.assertGreaterEqual(summary['discovery_seconds'], 0)
            self.assertGreaterEqual(summary['inspection_seconds'], 0)
            report_html = (report / '检查报告.html').read_text(encoding='utf-8')
            self.assertIn('推荐扫描', report_html)
            self.assertIn('Steam 游戏库', report_html)
            self.assertIn('自定义排除目录', report_html)
        self.assertEqual(results[0], results[1])
        self.assertEqual(before, {name: path.read_bytes() for name, path in self.files.items()})

    def test_cancel_saves_partial_report(self):
        cancelled = threading.Event()
        def notify(**info):
            cancelled.set()
        report = self.folder / 'stopped'
        summary = ppt_audit.scan([self.data], report, cancelled, notify)
        self.assertIn('已停止', summary['state'])
        self.assertTrue((report / '检查报告.html').exists())


class SettingsTests(unittest.TestCase):
    def setUp(self):
        import customtkinter as ctk
        from md3_ui import AuditApp
        self.ctk, self.App = ctk, AuditApp
        self.folder = RUN / self._testMethodName
        self.folder.mkdir(parents=True)
        self.engine = types.SimpleNamespace(scan=ppt_audit.scan, fixed_drives=lambda: ['C:\\', 'D:\\'],
                                            LABELS=ppt_audit.LABELS)
        self.open_app()

    def open_app(self):
        self.root = self.ctk.CTk()
        self.root.withdraw()
        self.root.attributes('-alpha', 0)
        self.app = self.App(self.root, self.engine, self.folder)

    def close_app(self):
        for timer in self.root.tk.call('after', 'info'):
            self.root.after_cancel(timer)
        self.root.destroy()

    def tearDown(self):
        self.close_app()

    def test_modes_and_exclusion_list_survive_restart(self):
        excluded = self.folder / '排除目录'
        excluded.mkdir()
        self.app.scan_mode_buttons['full'].invoke()
        self.app.exclusions_button.invoke()
        with patch('md3_ui.filedialog.askdirectory', return_value=str(excluded)):
            self.app.add_exclusion()
            self.app.add_exclusion()
        self.assertEqual(self.app.exclude_dirs, [path_key(excluded)])
        self.close_app()
        self.open_app()
        self.assertEqual(self.app.scan_mode, 'full')
        self.assertEqual(self.app.exclude_dirs, [path_key(excluded)])
        self.app.remove_exclusion(path_key(excluded))
        settings = json.loads(self.app.scan_settings_path.read_text(encoding='utf-8'))
        self.assertEqual(settings, dict(mode='full', exclude_dirs=[]))

    def test_scan_uses_selected_mode_and_exclusions(self):
        selected = self.folder / '资料'
        fixture(selected / '保留.pptx')
        excluded = selected / '排除'
        fixture(excluded / '跳过.pptx')
        self.app.select_all(False)
        self.app.folders.append(str(selected))
        self.app.exclude_dirs.append(str(excluded))
        self.app.set_scan_mode('full')
        self.app.render_folders()
        self.app.render_exclusions()
        self.app.start()
        self.assertEqual(self.app.scan_mode_buttons['full'].cget('state'), 'disabled')
        self.assertEqual(self.app.exclusion_remove_buttons[0].cget('state'), 'disabled')
        deadline = time.monotonic() + 10
        while self.app.state['running'] and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertFalse(self.app.state['running'])
        self.assertEqual(self.app.summary['scan_mode'], 'full')
        self.assertEqual(self.app.summary['checked'], 1)
        self.assertEqual(self.app.summary['explicit_roots'], [str(selected)])

    def test_options_and_start_fit_resized_window(self):
        self.root.deiconify()
        self.app.toggle_exclusions()
        for size in ('1180x780', '820x640', '1440x900'):
            self.root.geometry(size)
            self.root.update()
            for button in self.app.scan_mode_buttons.values():
                self.assertGreaterEqual(button.winfo_rootx(), self.root.winfo_rootx())
                self.assertLessEqual(button.winfo_rootx() + button.winfo_width(),
                                     self.root.winfo_rootx() + self.root.winfo_width())
            self.assertLessEqual(self.app.start_button.winfo_rooty() + self.app.start_button.winfo_height(),
                                 self.root.winfo_rooty() + self.root.winfo_height())


if __name__ == '__main__':
    RUN.mkdir(parents=True)
    with (RUN / '测试日志.txt').open('w', encoding='utf-8') as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromModule(__import__(__name__)))
    summary = dict(passed=result.wasSuccessful(), tests=result.testsRun,
                   failures=len(result.failures), errors=len(result.errors), output=str(RUN))
    (RUN / '测试结果.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))
    raise SystemExit(0 if result.wasSuccessful() else 1)
