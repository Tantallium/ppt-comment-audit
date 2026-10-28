"""只读检查 PowerPoint 传统批注作者编号。"""
import argparse
import csv
import ctypes
from datetime import datetime
import json
import os
from pathlib import Path
import re
import signal
import sys
import threading
import time
import xml.etree.ElementTree as ET
import zipfile
import zlib

MODERN = {'.pptx', '.pptm', '.ppsx', '.ppsm', '.potx', '.potm'}
LEGACY = {'.ppt', '.pps', '.pot'}
P_NS = {'http://schemas.openxmlformats.org/presentationml/2006/main',
        'http://purl.oclc.org/ooxml/presentationml/main'}
AUTHOR_TYPE = 'application/vnd.openxmlformats-officedocument.presentationml.commentAuthors+xml'
SKIP_NAMES = {'$recycle.bin', 'system volume information', '.git', 'node_modules',
              '__pycache__', '.venv'}
LABELS = {'duplicate': '发现重复编号', 'invalid': '作者编号或记录异常',
          'clear': '未发现本次编号问题', 'uncheckable': '无法检查',
          'unsupported': '旧格式，未检查'}
FIELDS = ['文件路径', '结果', '作者记录数', '不同编号数', '重复编号组数',
          '多余重复记录数', '末尾追加冲突特征', '保存软件标记', 'WPS构建标记', '说明']


def application_directory():
    return Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent


def fixed_drives():
    kernel = ctypes.windll.kernel32
    kernel.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
    mask = kernel.GetLogicalDrives()
    return [f'{chr(65+i)}:\\' for i in range(26)
            if mask & (1 << i) and kernel.GetDriveTypeW(f'{chr(65+i)}:\\') == 3]


class NoDTDTreeBuilder(ET.TreeBuilder):
    def doctype(self, name, pubid, system):
        raise ValueError('相关 XML 包含 DTD，跳过。')


def read_xml(archive, name):
    if archive.getinfo(name).file_size > 32 * 1024 * 1024:
        raise ValueError(f'相关 XML 超过 32 MB，跳过：{name}')
    data = archive.read(name)
    return ET.fromstring(data, parser=ET.XMLParser(target=NoDTDTreeBuilder()))


def inspect_file(path):
    result = dict(path=str(path), status='clear', authors=0, unique=0,
                  duplicate_groups=0, duplicate_records=0, append_pattern=False,
                  application='', wps_build='', note='', parts=[])
    if path.suffix.lower() in LEGACY:
        result.update(status='unsupported', note='二进制旧格式，需要另行转换后检查。')
        return result
    try:
        with zipfile.ZipFile(path, 'r') as archive:
            infos = archive.infolist()
            names = {info.filename for info in infos}
            if len(names) != len(infos):
                raise ValueError('ZIP 内部存在重名条目，不能可靠检查。')
            types = read_xml(archive, '[Content_Types].xml')
            author_parts = {item.attrib['PartName'].lstrip('/') for item in types
                            if item.attrib.get('ContentType') == AUTHOR_TYPE}
            if 'ppt/commentAuthors.xml' in names:
                author_parts.add('ppt/commentAuthors.xml')
            issues = []
            for name in sorted(author_parts):
                root = read_xml(archive, name)
                namespace = root.tag[1:].split('}')[0] if root.tag.startswith('{') else ''
                if namespace not in P_NS or root.tag != f'{{{namespace}}}cmAuthorLst':
                    raise ValueError(f'批注作者列表的 XML 类型不符：{name}')
                records = list(root.findall(f'{{{namespace}}}cmAuthor'))
                groups, invalid, repeat_positions = {}, [], []
                numbers = []
                for position, record in enumerate(records, 1):
                    raw = record.get('id', '').strip()
                    if not re.fullmatch(r'[+-]?[0-9]+', raw) or not 0 <= int(raw) <= 4294967295:
                        invalid.append(position)
                        numbers.append(None)
                        continue
                    number = int(raw)
                    numbers.append(number)
                    if number in groups:
                        repeat_positions.append(position)
                    groups.setdefault(number, []).append(position)
                duplicates = {str(k): v for k, v in groups.items() if len(v) > 1}
                tail = bool(repeat_positions) and not invalid and repeat_positions == list(
                    range(repeat_positions[0], len(records) + 1))
                if tail:
                    suffix = numbers[repeat_positions[0] - 1:]
                    tail = suffix == list(range(suffix[0], suffix[0] + len(suffix)))
                detail = dict(part=name, author_count=len(records), unique_ids=len(groups),
                              duplicates=duplicates, invalid_id_positions=invalid,
                              append_pattern=tail)
                result['parts'].append(detail)
                result['authors'] += len(records)
                result['unique'] += len(groups)
                result['duplicate_groups'] += len(duplicates)
                result['duplicate_records'] += len(repeat_positions)
                result['append_pattern'] |= tail
                if duplicates:
                    result['status'] = 'duplicate'
                    issues.append(f'{name}：{len(duplicates)} 组重复编号，{len(repeat_positions)} 条重复记录')
                if invalid:
                    if result['status'] != 'duplicate':
                        result['status'] = 'invalid'
                    issues.append(f'{name}：{len(invalid)} 条编号缺失、非法或超出范围')
            for name, destination, local_tag in [('docProps/app.xml', 'application', 'Application'),
                                                 ('docProps/custom.xml', 'wps_build', 'KSOProductBuildVer')]:
                if name not in names:
                    continue
                try:
                    root = read_xml(archive, name)
                    for element in root.iter():
                        if element.tag.rsplit('}', 1)[-1] == local_tag:
                            result[destination] = element.text or ''
                        elif element.get('name') == local_tag:
                            result[destination] = ''.join(element.itertext())
                except (ET.ParseError, ValueError, OSError, RuntimeError, EOFError,
                        zlib.error, zipfile.BadZipFile) as exc:
                    issues.append(f'保存软件元数据无法读取：{exc}')
            if not author_parts:
                issues.append('未包含传统批注作者列表；本次编号问题不适用。')
            result['note'] = '；'.join(issues)
    except (OSError, ValueError, KeyError, ET.ParseError, RuntimeError,
            NotImplementedError, EOFError, zlib.error, zipfile.BadZipFile) as exc:
        result.update(status='uncheckable', note=f'{type(exc).__name__}: {exc}')
        if isinstance(exc, zipfile.BadZipFile):
            result['note'] += '（可能是加密的 Office 文件、非标准格式或压缩包损坏。）'
    return result


def system_paths():
    paths = {os.path.normcase(os.path.abspath(value)) for key in
             ('SystemRoot', 'ProgramFiles', 'ProgramFiles(x86)')
             if (value := os.environ.get(key))}
    paths.add(os.path.normcase(str(application_directory() / '验证记录')))
    return paths


def discover(roots, record_skip, cancelled, progress):
    excluded = system_paths()
    seen = set()
    for root in roots:
        stack = [Path(root).absolute()]
        while stack and not cancelled.is_set():
            path = stack.pop()
            key = os.path.normcase(str(path))
            if key in seen:
                continue
            seen.add(key)
            try:
                stat = path.lstat()
                attributes = getattr(stat, 'st_file_attributes', 0)
                # 不跟随目录联接/符号链接，不下载仅存云端的文件。
                if attributes & (0x1000 | 0x40000 | 0x400000):
                    record_skip(path, '云端占位或离线项目')
                    continue
                if path.is_symlink() or attributes & 0x400:
                    record_skip(path, '链接或重解析点')
                    continue
                if path.is_dir():
                    if path.name.lower() in SKIP_NAMES or key in excluded:
                        record_skip(path, '排除目录（系统、回收站、开发依赖或工具测试材料）')
                        continue
                    progress(directory=str(path))
                    with os.scandir(path) as entries:
                        for entry in entries:
                            if cancelled.is_set():
                                break
                            if entry.name.startswith('~$'):
                                continue
                            if entry.is_symlink():
                                record_skip(entry.path, '链接或重解析点')
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(Path(entry.path))
                            elif Path(entry.name).suffix.lower() in MODERN | LEGACY:
                                stack.append(Path(entry.path))
                elif path.suffix.lower() in MODERN | LEGACY:
                    yield path
            except OSError as exc:
                record_skip(path, f'无法访问：{exc}')


def write_html(folder, summary, results):
    from ppt_report import write_html as render_report
    render_report(folder, summary, results, LABELS)


def write_markdown(folder, summary, results):
    problems = [r for r in results if r['status'] in {'duplicate', 'invalid'}]
    unchecked = [r for r in results if r['status'] == 'uncheckable']
    lines = ['# PPT 待修复列表', '',
             f'- 扫描时间：{summary["started_at"]} 至 {summary["finished_at"]}',
             f'- 扫描范围：{", ".join(summary["roots"])}；状态：{summary["state"]}。',
             f'- 共检查/登记 {summary["checked"]} 个演示文件，确认编号问题 {len(problems)} 个。',
             f'- 未发现本次编号问题 {summary["counts"]["clear"]} 个；无法检查 {len(unchecked)} 个；'
             f'旧格式未检查 {summary["counts"]["unsupported"]} 个。',
             f'- 跳过或无法访问 {summary["skipped"]} 个项目（目录跳过包含其全部子项）。', '',
             '本次只读扫描传统批注作者编号，未修复任何源文件；未调用 PowerPoint 逐一验证打开。', '',
             '## 已确认需要修复的编号问题', '']

    def link(path):
        label = path.replace('[', '\\[').replace(']', '\\]').replace('|', '&#124;')
        target = path.replace('\\', '/').replace('>', '%3E').replace('<', '%3C')
        return f'[{label}](<{target}>)'

    if problems:
        lines += ['| 序号 | 文件路径 | 重复编号组数 | 重复记录数 | 末尾追加冲突特征 |',
                  '| --- | --- | ---: | ---: | --- |']
        for index, result in enumerate(problems, 1):
            pattern = '符合' if result['append_pattern'] else '未标记'
            if result['status'] == 'invalid':
                pattern = '编号缺失、非法或超出范围'
            lines.append(f'| {index} | {link(result["path"])} | {result["duplicate_groups"]} | '
                         f'{result["duplicate_records"]} | {pattern} |')
    else:
        lines.append('未发现符合本次检测规则的编号问题。')
    lines += ['', '“末尾追加冲突特征”指重复记录连续位于列表末尾，且编号连续递增；不单独作为软件归因证据。', '',
              '## 无法检查，待另行确认', '']
    if unchecked:
        for result in unchecked:
            lines.append(f'- {link(result["path"])}：{result["note"]}')
    else:
        lines.append('无。')
    lines += ['', '## 范围说明', '',
              '自动排除 Windows、Program Files、回收站、系统卷信息、开发依赖目录、本工具验证材料、链接及重解析点、离线或云端占位项目。'
              '无权读取的项目跳过；Office 锁定文件不检查。', '',
              '此列表只覆盖本次实际可检查的文件；“未发现本次编号问题”不代表文件不存在其他问题。', '']
    (folder / '待修复列表.md').write_text('\n'.join(lines), encoding='utf-8')


def csv_text(value):
    # CSV 引号不能阻止 Excel 将外部文本解释为公式。
    if isinstance(value, str) and (value.startswith(('\t', '\r', '\n'))
                                   or value.lstrip().startswith(('=', '+', '-', '@'))):
        return "'" + value
    return value


def scan(roots, output, cancelled=None, notify=None):
    cancelled = cancelled or threading.Event()
    notify = notify or (lambda **kwargs: None)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    summary = dict(started_at=datetime.now().astimezone().isoformat(), roots=[str(r) for r in roots],
                   exclusions=sorted(SKIP_NAMES | system_paths()), directories=0, skipped=0,
                   counts={key: 0 for key in LABELS}, state='扫描中')
    results = []
    last_notify = 0
    with (output / '未检查项目.jsonl').open('w', encoding='utf-8') as skipped_file, \
         (output / '逐文件详情.jsonl').open('w', encoding='utf-8') as detail_file, \
         (output / '检查清单.csv').open('w', encoding='utf-8-sig', newline='') as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(FIELDS)

        def record_skip(path, reason):
            summary['skipped'] += 1
            skipped_file.write(json.dumps(dict(path=str(path), reason=reason), ensure_ascii=False) + '\n')
            skipped_file.flush()

        def progress(**info):
            nonlocal last_notify
            if 'directory' in info:
                summary['directories'] += 1
            if time.monotonic() - last_notify >= 0.5:
                notify(checked=len(results), directories=summary['directories'],
                       skipped=summary['skipped'], counts=summary['counts'].copy(), **info)
                last_notify = time.monotonic()

        for path in discover(roots, record_skip, cancelled, progress):
            result = inspect_file(path)
            results.append(result)
            summary['counts'][result['status']] += 1
            detail_file.write(json.dumps(result, ensure_ascii=False) + '\n')
            detail_file.flush()
            writer.writerow([csv_text(value) for value in [
                             result['path'], LABELS[result['status']], result['authors'], result['unique'],
                             result['duplicate_groups'], result['duplicate_records'],
                             '符合' if result['append_pattern'] else '未标记', result['application'],
                             result['wps_build'], result['note']]])
            csv_file.flush()
            progress(file=str(path))
    summary.update(state='已停止，报告为部分结果' if cancelled.is_set() else '完成',
                   finished_at=datetime.now().astimezone().isoformat(), checked=len(results),
                   seconds=round(time.monotonic() - started, 2))
    (output / '扫描摘要.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    write_markdown(output, summary, results)
    write_html(output, summary, results)
    return summary


def launch_gui(window=None):
    from types import SimpleNamespace
    from md3_ui import launch_gui as open_interface
    engine = SimpleNamespace(scan=scan, fixed_drives=fixed_drives, LABELS=LABELS)
    return open_interface(engine, application_directory(), window)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paths', nargs='*', help='一个或多个文件/文件夹/磁盘根路径')
    parser.add_argument('--all-fixed', action='store_true', help='检查全部本地固定磁盘')
    parser.add_argument('--output', type=Path, help='新的报告目录，不覆盖已有目录')
    parser.add_argument('--verify-gui', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.verify_gui:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.after(500, root.destroy)
        launch_gui(root)
        args.verify_gui.write_text(json.dumps(dict(gui_ready=True, frozen=bool(getattr(sys, 'frozen', False)),
                                                  application_directory=str(application_directory())), ensure_ascii=False), encoding='utf-8')
        return
    if not args.paths and not args.all_fixed:
        launch_gui()
        return
    roots = (fixed_drives() if args.all_fixed else []) + args.paths
    output = args.output or application_directory() / '报告' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    output.parent.mkdir(parents=True, exist_ok=True)
    cancelled = threading.Event()

    last_print = 0

    def progress(**data):
        nonlocal last_print
        if sys.stdout is not None and time.monotonic() - last_print >= 15:
            print(f'目录 {data["directories"]} | 文件 {data["checked"]} | 编号问题 '
                  f'{data["counts"]["duplicate"] + data["counts"]["invalid"]}', flush=True)
            last_print = time.monotonic()

    signal.signal(signal.SIGINT, lambda *_: cancelled.set())
    summary = scan(roots, output, cancelled, progress)
    if sys.stdout is not None:
        print(json.dumps(dict(report=str(output), **summary), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
