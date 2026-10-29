"""原位写回、备份、只读属性与失败保留测试。"""
from datetime import datetime
import json
from pathlib import Path
import shutil
import stat
import struct
import unittest
from unittest.mock import patch
import zipfile

import ppt_audit
import ppt_repair
import test_number_repair as fixtures

RUN = fixtures.BASE / '验证记录' / ('逻辑验证-' + datetime.now().strftime('%H%M%S'))
fixtures.RUN = RUN


class InPlaceTests(fixtures.RepairTests):
    def test_repair_original_with_exact_backup_and_readonly_attribute(self):
        source = self.package([1, 1])
        original = source.read_bytes()
        source.chmod(stat.S_IREAD)
        result = ppt_repair.repair_batch([source], self.folder / '记录', in_place=True)
        record = result['records'][0]
        self.assertEqual(record['status'], 'fixed')
        self.assertEqual(record['output'], str(source))
        self.assertEqual(Path(record['backup']).read_bytes(), original)
        self.assertEqual(ppt_audit.inspect_file(source)['status'], 'clear')
        self.assertTrue(source.stat().st_file_attributes & 1)
        self.assertFalse(list(self.folder.glob('.pptrepair-*')))
        self.verify_members(Path(record['backup']), source, {'ppt/commentAuthors.xml'})
        restored = self.folder / '恢复验证.pptx'
        shutil.copy2(record['backup'], restored)
        self.assertEqual(restored.read_bytes(), original)

    def test_backup_failure_does_not_write_original(self):
        source = self.package([1, 1])
        original = source.read_bytes()
        real_open = Path.open

        def open_file(path, *args, **kwargs):
            if ppt_repair.BACKUP_FOLDER in path.parts and path.name.endswith('.partial'):
                raise PermissionError('备份位置无法写入')
            return real_open(path, *args, **kwargs)

        with patch.object(Path, 'open', open_file):
            result = ppt_repair.repair_batch([source], self.folder / '记录', in_place=True)
        self.assertEqual(result['counts']['failed'], 1)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(result['records'][0]['backup'], '')

    def test_writeback_failure_preserves_original_backup_and_readonly(self):
        source = self.package([1, 1])
        original = source.read_bytes()
        source.chmod(stat.S_IREAD)
        with patch('ppt_repair.os.replace', side_effect=PermissionError('文件被占用')):
            result = ppt_repair.repair_batch([source], self.folder / '记录', in_place=True)
        record = result['records'][0]
        self.assertEqual(record['status'], 'failed')
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(Path(record['backup']).read_bytes(), original)
        self.assertTrue(source.stat().st_file_attributes & 1)
        self.assertFalse(list(self.folder.glob('.pptrepair-*')))
        retained = list(Path(record['backup']).parent.glob('*_未写回修复版.pptx'))
        self.assertEqual(len(retained), 1)
        self.assertEqual(ppt_audit.inspect_file(retained[0])['status'], 'clear')

    def test_corrupt_package_does_not_replace_original(self):
        source = self.package([1, 1])
        with zipfile.ZipFile(source) as z:
            offset = z.getinfo('ppt/media/image1.png').header_offset
        data = bytearray(source.read_bytes())
        name, extra = struct.unpack_from('<HH', data, offset + 26)
        data[offset + 30 + name + extra] ^= 1
        source.write_bytes(data)
        result = ppt_repair.repair_batch([source], self.folder / '记录', in_place=True)
        self.assertEqual(result['counts']['failed'], 1)
        self.assertEqual(source.read_bytes(), bytes(data))
        self.assertEqual(Path(result['records'][0]['backup']).read_bytes(), bytes(data))
        self.assertFalse(list(self.folder.glob('.pptrepair-*')))

    def test_changed_source_is_not_overwritten(self):
        source = self.package([1, 1])
        original = source.read_bytes()
        repair = ppt_repair.repair_file

        def concurrent_save(*args):
            result = repair(*args)
            source.write_bytes(original + b'edited while repairing')
            return result

        with patch('ppt_repair.repair_file', side_effect=concurrent_save):
            result = ppt_repair.repair_batch([source], self.folder / '记录', in_place=True)
        self.assertEqual(result['counts']['failed'], 1)
        self.assertIn('发生变化', result['records'][0]['note'])
        self.assertEqual(source.read_bytes(), original + b'edited while repairing')

    def test_own_backups_are_excluded_from_scan(self):
        source = self.package([1, 1])
        ppt_repair.repair_batch([source], self.folder / '记录', in_place=True)
        summary = ppt_audit.scan([self.folder], self.folder / '复查')
        self.assertEqual(summary['checked'], 1)
        self.assertEqual(summary['counts']['duplicate'], 0)
        skipped = (self.folder / '复查/未检查项目.jsonl').read_text(encoding='utf-8')
        self.assertIn(ppt_repair.BACKUP_FOLDER, skipped)

    def test_same_names_and_copy_mode_remain_supported(self):
        second = self.folder / '另一个目录'
        second.mkdir()
        paths = [self.package([1, 1]), self.package([2, 2], folder=second)]
        originals = [p.read_bytes() for p in paths]
        copies = ppt_repair.repair_batch(paths, self.folder / '另存')
        self.assertEqual([p.read_bytes() for p in paths], originals)
        self.assertTrue(all(r['mode'] == 'copy' for r in copies['records']))
        result = ppt_repair.repair_batch(paths, self.folder / '原位', in_place=True)
        self.assertEqual(result['counts']['fixed'], 2)
        self.assertNotEqual(result['records'][0]['backup'], result['records'][1]['backup'])
        self.assertEqual([Path(r['backup']).read_bytes() for r in result['records']], originals)



if __name__ == '__main__':
    RUN.mkdir(parents=True)
    tests = unittest.TestSuite(InPlaceTests(name) for name in InPlaceTests.__dict__ if name.startswith('test_'))
    with (RUN / '测试日志.txt').open('w', encoding='utf-8') as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(tests)
    summary = dict(tests=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                   successful=result.wasSuccessful(), output=str(RUN))
    (RUN / '测试结果.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))
    raise SystemExit(0 if result.wasSuccessful() else 1)
