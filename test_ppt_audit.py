"""关键检测规则及报告行为测试。测试样本保留在验证记录目录。"""
from pathlib import Path
from datetime import datetime
import json
import threading
import unittest
import zipfile

from ppt_audit import inspect_file, scan

HERE = Path(__file__).resolve().parent
RUN = HERE / '验证记录' / ('回归测试-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
FIXTURES = RUN / '合成样本'
NS = 'http://schemas.openxmlformats.org/presentationml/2006/main'
CONTENT = '''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Override PartName="/ppt/commentAuthors.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.commentAuthors+xml"/>
</Types>'''


def fixture(name, authors=None, xml=None, content=CONTENT):
    FIXTURES.mkdir(parents=True, exist_ok=True)
    path = FIXTURES / name
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', content)
        if authors is not None:
            records = ''.join(f'<p:cmAuthor id="{number}" name="测试" initials="T"/>' for number in authors)
            xml = f'<p:cmAuthorLst xmlns:p="{NS}">{records}</p:cmAuthorLst>'
        if xml is not None:
            archive.writestr('ppt/commentAuthors.xml', xml)
    return path


class DetectorTests(unittest.TestCase):
    def setUp(self):
        FIXTURES.mkdir(parents=True, exist_ok=True)

    def test_unique_and_no_authors(self):
        self.assertEqual(inspect_file(fixture('正常.pptx', [0, 1, 42]))['status'], 'clear')
        self.assertEqual(inspect_file(fixture('无批注.pptx', content='<Types/>'))['status'], 'clear')

    def test_appended_sequence(self):
        result = inspect_file(fixture('末尾追加.pptx', [10, 2, 3, 2, 3]))
        self.assertEqual(result['duplicate_groups'], 2)
        self.assertEqual(result['duplicate_records'], 2)
        self.assertTrue(result['append_pattern'])
        self.assertEqual(result['parts'][0]['duplicates']['2'], [2, 4])

    def test_non_tail_and_numeric_equivalence(self):
        result = inspect_file(fixture('非末尾重复.PPTX', [1, '01', 2, 1]))
        self.assertEqual(result['duplicate_groups'], 1)
        self.assertEqual(result['duplicate_records'], 2)
        self.assertFalse(result['append_pattern'])

    def test_invalid_and_missing_ids(self):
        result = inspect_file(fixture('非法编号.pptx', [-1, 4294967296, 'abc', '']))
        self.assertEqual(result['status'], 'invalid')
        self.assertEqual(len(result['parts'][0]['invalid_id_positions']), 4)
        result = inspect_file(fixture('缺少编号.pptx', xml=f'<p:cmAuthorLst xmlns:p="{NS}"><p:cmAuthor/></p:cmAuthorLst>'))
        self.assertEqual(result['status'], 'invalid')

    def test_corrupt_missing_part_and_legacy(self):
        broken = FIXTURES / '损坏.pptx'
        broken.write_bytes(b'not an archive')
        self.assertEqual(inspect_file(broken)['status'], 'uncheckable')
        self.assertEqual(inspect_file(fixture('缺少部件.pptx'))['status'], 'uncheckable')
        self.assertEqual(inspect_file(fixture('XML损坏.pptx', xml='<broken'))['status'], 'uncheckable')
        self.assertEqual(inspect_file(Path('旧文件.ppt'))['status'], 'unsupported')

    def test_metadata_does_not_imply_error(self):
        path = fixture('WPS正常.pptm', [0, 1])
        with zipfile.ZipFile(path, 'a') as archive:
            archive.writestr('docProps/app.xml', '<Properties><Application>WPS 演示</Application></Properties>')
            archive.writestr('docProps/custom.xml', '<Properties><property name="KSOProductBuildVer"><value>12.1</value></property></Properties>')
        result = inspect_file(path)
        self.assertEqual(result['status'], 'clear')
        self.assertEqual(result['application'], 'WPS 演示')
        self.assertEqual(result['wps_build'], '12.1')

    def test_batch_overlap_reports_and_cancellation(self):
        path = fixture('报告验证.ppsx', [1, 1])
        before = path.stat()
        output = RUN / '批量报告'
        summary = scan([path, path.parent], output)
        self.assertEqual(summary['checked'], len(list(path.parent.glob('*.pptx'))) +
                         len(list(path.parent.glob('*.pptm'))) + len(list(path.parent.glob('*.ppsx'))))
        self.assertEqual(before.st_mtime_ns, path.stat().st_mtime_ns)
        self.assertEqual(before.st_size, path.stat().st_size)
        self.assertTrue((output / '检查报告.html').exists())
        markdown = (output / '待修复列表.md').read_text(encoding='utf-8')
        self.assertIn(str(path), markdown)
        self.assertIn('已确认需要修复的编号问题', markdown)
        self.assertEqual(json.loads((output / '扫描摘要.json').read_text(encoding='utf-8'))['state'], '完成')
        with self.assertRaises(FileExistsError):
            scan([path], output)
        cancelled = threading.Event()
        cancelled.set()
        partial = scan([path], RUN / '停止扫描报告', cancelled)
        self.assertEqual(partial['checked'], 0)
        self.assertIn('已停止', partial['state'])

    def test_large_author_list(self):
        original = fixture('大量作者重复.pptx', list(range(894)) + list(range(95)))
        repaired = fixture('大量作者正常.pptx', range(989))
        for path, expected in [(original, 95), (repaired, 0)]:
            before = path.stat()
            result = inspect_file(path)
            self.assertEqual(result['duplicate_records'], expected)
            self.assertEqual(result['authors'], 989)
            self.assertEqual(result['append_pattern'], bool(expected))
            self.assertEqual(before.st_mtime_ns, path.stat().st_mtime_ns)
            self.assertEqual(before.st_size, path.stat().st_size)


if __name__ == '__main__':
    unittest.main(verbosity=2)
