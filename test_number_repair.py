"""编号修复、批注引用与原文件保护的合成样本回归。"""
from datetime import datetime
import json
from pathlib import Path
import struct
import threading
import unittest
import xml.etree.ElementTree as ET
import zipfile

import ppt_audit
from ppt_repair import NeedsReview, repair_batch, repair_file

BASE = Path(__file__).resolve().parent
RUN = BASE / '验证记录' / ('回归-' + datetime.now().strftime('%H%M%S'))
NS = 'http://schemas.openxmlformats.org/presentationml/2006/main'


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.folder = RUN / type(self).__name__ / self._testMethodName
        self.folder.mkdir(parents=True)

    def package(self, ids, comments=None, author_xml=None, encoding='utf-8', name='样本.pptx', folder=None):
        path = (folder or self.folder) / name
        if author_xml is None:
            entries = ''.join('<p:cmAuthor ' + (f'id="{i}" ' if i is not None else '') +
                              'name="甲" initials="J" lastIdx="2" clrIdx="0"/>' for i in ids)
            author_xml = f'<?xml version="1.0" encoding="{encoding}"?><p:cmAuthorLst xmlns:p="{NS}">{entries}</p:cmAuthorLst>'
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_STORED) as z:
            z.writestr('[Content_Types].xml', '<Types/>')
            z.writestr('ppt/commentAuthors.xml', author_xml.encode(encoding))
            z.writestr('ppt/slides/slide1.xml', '<slide><text>文字保持不变</text></slide>')
            z.writestr('ppt/media/image1.png', bytes(range(256)) * 32)
            if comments is not None:
                nodes = ''.join(f'<p:cm authorId="{i}" idx="1"><p:text>保留批注正文</p:text></p:cm>' for i in comments)
                z.writestr('ppt/comments/comment1.xml', f'<p:cmLst xmlns:p="{NS}">{nodes}</p:cmLst>')
            z.comment = b'preserve archive comment'
        return path

    def verify_members(self, original, repaired, changed):
        with zipfile.ZipFile(original) as a, zipfile.ZipFile(repaired) as b:
            self.assertEqual(a.namelist(), b.namelist())
            self.assertEqual(a.comment, b.comment)
            for info in a.infolist():
                other = b.getinfo(info.filename)
                self.assertEqual((info.date_time, info.external_attr, info.compress_type),
                                 (other.date_time, other.external_attr, other.compress_type))
                if info.filename in changed:
                    continue
                with a.open(info) as reader, b.open(info.filename) as writer:
                    while data := reader.read(1024 * 1024):
                        self.assertEqual(data, writer.read(len(data)), info.filename)
                    self.assertEqual(writer.read(1), b'')
            self.assertIsNone(b.testzip())

    def test_duplicate_repairs_only_id_attributes(self):
        source = self.package([0, 1, 1, 2, 2])
        before = source.read_bytes()
        out = self.folder / '修复.pptx'
        record = repair_file(source, out)
        self.assertEqual(record['status'], 'fixed')
        self.assertEqual(len(record['changes']), 2)
        self.assertEqual(ppt_audit.inspect_file(out)['status'], 'clear')
        self.assertEqual(source.read_bytes(), before)
        self.verify_members(source, out, {'ppt/commentAuthors.xml'})

    def test_invalid_missing_max_id_and_unrelated_comment_reference(self):
        source = self.package([0, 4294967295, 4294967295, -1, None, 'bad'], comments=[0])
        out = self.folder / '修复.pptx'
        result = repair_file(source, out)
        self.assertEqual(len(result['changes']), 4)
        self.assertEqual([r['new'] for r in result['changes']], [1, 2, 3, 4])
        self.assertEqual(result['comment_updates'], 0)
        self.verify_members(source, out, {'ppt/commentAuthors.xml'})

    def test_referenced_duplicate_requires_author_confirmation(self):
        source = self.package([1, 1], comments=[1])
        out = self.folder / '修复.pptx'
        with self.assertRaisesRegex(NeedsReview, '作者归属'):
            repair_file(source, out)
        self.assertFalse(out.exists())
        self.assertFalse(out.with_name(out.name + '.partial').exists())

    def test_unique_invalid_reference_is_updated(self):
        source = self.package([7, -1], comments=[-1, 7])
        out = self.folder / '修复.pptx'
        result = repair_file(source, out)
        self.assertEqual(result['comment_updates'], 1)
        with zipfile.ZipFile(source) as a, zipfile.ZipFile(out) as b:
            original = a.read('ppt/comments/comment1.xml')
            expected = original.replace(b'authorId="-1"', b'authorId="8"')
            self.assertEqual(b.read('ppt/comments/comment1.xml'), expected)
        self.verify_members(source, out, {'ppt/commentAuthors.xml', 'ppt/comments/comment1.xml'})

    def test_xml_encodings_and_lexical_content(self):
        for index, encoding in enumerate(['utf-8', 'utf-16', 'utf-16-le', 'utf-16-be']):
            declaration = 'UTF-8' if encoding == 'utf-8' else 'UTF-16'
            xml = (f'<?xml version="1.0" encoding="{declaration}"?>\n'
                   f'<cmAuthorLst xmlns="{NS}"><!-- <cmAuthor id="1"/> -->'
                   '<cmAuthor name="甲 &amp; 乙 > 丙" id = \'1\' />'
                   '<cmAuthor id = \'01\' name="乙"/><cmAuthor name="丙"/>'
                   '</cmAuthorLst>')
            source = self.package([], author_xml=xml, encoding=encoding, name=f'编码{index}.pptx')
            out = self.folder / f'编码{index}_修复.pptx'
            result = repair_file(source, out)
            expected = xml.replace("id = '01'", "id = '2'").replace('<cmAuthor name="丙"/>', '<cmAuthor name="丙" id="3"/>')
            with zipfile.ZipFile(out) as z:
                self.assertEqual(z.read('ppt/commentAuthors.xml'), expected.encode(encoding))
            self.assertEqual(len(result['changes']), 2)

    def test_character_reference_id_is_handled(self):
        source = self.package(['1', '&#49;', '01'])
        out = self.folder / '修复.pptx'
        record = repair_file(source, out)
        self.assertEqual(len(record['changes']), 2)
        self.assertEqual(ppt_audit.inspect_file(out)['unique'], 3)

    def test_existing_destination_is_preserved(self):
        source = self.package([1, 1])
        out = self.folder / '修复.pptx'
        out.write_bytes(b'keep existing output')
        with self.assertRaises(FileExistsError):
            repair_file(source, out)
        self.assertEqual(out.read_bytes(), b'keep existing output')
        with self.assertRaises(FileExistsError):
            repair_file(source, source)

    def test_batch_same_names_cancellation_and_record(self):
        second = self.folder / '另一个目录'
        second.mkdir()
        paths = [self.package([1, 1]), self.package([2, 2], folder=second)]
        summary = repair_batch(paths, self.folder / '批量')
        self.assertEqual(summary['counts']['fixed'], 2)
        self.assertNotEqual(summary['records'][0]['output'], summary['records'][1]['output'])
        cancelled = threading.Event()
        summary = repair_batch(paths, self.folder / '停止', cancelled,
                               lambda **_: cancelled.set())
        self.assertEqual(summary['processed'], 1)
        self.assertIn('已停止', summary['state'])
        self.assertTrue((self.folder / '停止/修复记录.json').is_file())

    def test_corrupt_payload_never_becomes_successful_output(self):
        source = self.package([1, 1])
        with zipfile.ZipFile(source) as z:
            offset = z.getinfo('ppt/media/image1.png').header_offset
        data = bytearray(source.read_bytes())
        name, extra = struct.unpack_from('<HH', data, offset + 26)
        data[offset + 30 + name + extra] ^= 1
        source.write_bytes(data)
        result = repair_batch([source], self.folder / '结果')
        self.assertEqual(result['counts']['failed'], 1)
        self.assertFalse(list((self.folder / '结果').glob('*.pptx')))
        self.assertEqual(source.read_bytes(), bytes(data))

    def test_clear_file_does_not_create_duplicate_copy(self):
        source = self.package([1, 2])
        out = self.folder / '修复.pptx'
        self.assertEqual(repair_file(source, out)['status'], 'unchanged')
        self.assertFalse(out.exists())



if __name__ == '__main__':
    RUN.mkdir(parents=True)
    with (RUN / '测试日志.txt').open('w', encoding='utf-8') as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(RepairTests))
    summary = dict(tests=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                   successful=result.wasSuccessful(), output=str(RUN))
    (RUN / '测试结果.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))
    raise SystemExit(0 if result.wasSuccessful() else 1)
