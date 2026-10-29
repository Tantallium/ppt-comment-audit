"""修复传统批注作者编号，支持另存副本或备份后原位写回。"""
from collections import Counter
from copy import copy
import csv
from datetime import datetime
import os
from pathlib import Path
import re
import shutil
import stat
import threading
from uuid import uuid4
from xml.parsers import expat
import zipfile
import json

from ppt_audit import AUTHOR_TYPE, MODERN, P_NS, csv_text, inspect_file, read_xml

MAX_ID = 4294967295
COMMENT_TYPE = 'application/vnd.openxmlformats-officedocument.presentationml.comments+xml'
STATUS = dict(fixed='修复成功', unchanged='无需修复', needs_review='需人工确认', failed='修复失败')
BACKUP_FOLDER = 'PPT编号修复备份'
ATTRIBUTE = re.compile(r'''\s+([^\s=/>]+)\s*=\s*(["'])(.*?)\2''', re.S)


class NeedsReview(ValueError):
    pass


def id_key(value):
    if value is None or not value.strip():
        return None
    value = value.strip()
    return ('number', int(value)) if re.fullmatch(r'[+-]?[0-9]+', value) else ('text', value)


def valid_id(key):
    return key is not None and key[0] == 'number' and 0 <= key[1] <= MAX_ID


def xml_encoding(data):
    if data.startswith(b'\xff\xfe') or data[:2] == b'<\x00':
        return 'utf-16-le'
    if data.startswith(b'\xfe\xff') or data[:2] == b'\x00<':
        return 'utf-16-be'
    declaration = re.search(br'''<\?xml[^>]*encoding\s*=\s*["']([^"']+)''', data[:200])
    return declaration.group(1).decode('ascii') if declaration else 'utf-8'


def xml_records(data, local_name):
    """取得实际 XML 元素的字节位置，忽略注释与扩展命名空间。"""
    parser = expat.ParserCreate(namespace_separator='}')
    wanted = {namespace + '}' + local_name for namespace in P_NS}
    records = []

    def start(name, attributes):
        if name in wanted:
            records.append((attributes, parser.CurrentByteIndex))

    def reject_dtd(*_):
        raise NeedsReview('相关 XML 含 DTD，无法自动修复。')

    parser.StartElementHandler = start
    parser.StartDoctypeDeclHandler = reject_dtd
    parser.Parse(data, True)
    return records


def replace_attributes(data, changes):
    """只替换属性值，不重新序列化 XML 或改写命名空间。"""
    encoding = xml_encoding(data)
    unit = 2 if encoding.lower().replace('_', '-').startswith('utf-16') else 1
    double, single, close = (value.encode(encoding) for value in ['"', "'", '>'])
    for start, attribute, number in sorted(changes, reverse=True):
        quote = None
        end = start
        while end < len(data):
            token = data[end:end + unit]
            end += unit
            if quote:
                if token == quote:
                    quote = None
            elif token in (double, single):
                quote = token
            elif token == close:
                break
        tag = data[start:end].decode(encoding)
        match = next((m for m in ATTRIBUTE.finditer(tag) if m.group(1) == attribute), None)
        if match:
            tag = tag[:match.start(3)] + str(number) + tag[match.end(3):]
        else:
            point = len(tag) - (2 if tag.endswith('/>') else 1)
            tag = tag[:point] + f' {attribute}="{number}"' + tag[point:]
        data = data[:start] + tag.encode(encoding) + data[end:]
    return data


def plan_changes(archive):
    types = read_xml(archive, '[Content_Types].xml')
    authors = {item.attrib['PartName'].lstrip('/') for item in types
               if item.attrib.get('ContentType') == AUTHOR_TYPE}
    if 'ppt/commentAuthors.xml' in archive.namelist():
        authors.add('ppt/commentAuthors.xml')
    comments = {item.attrib['PartName'].lstrip('/') for item in types
                if item.attrib.get('ContentType') == COMMENT_TYPE}
    comments.update(name for name in archive.namelist()
                    if name.startswith('ppt/comments/') and name.endswith('.xml'))
    data = {}
    author_records, comment_records = [], []
    for name, local_name, destination in [(p, 'cmAuthor', author_records) for p in sorted(authors)] + [
            (p, 'cm', comment_records) for p in sorted(comments)]:
        read_xml(archive, name)
        data[name] = archive.read(name)
        destination.extend((name, attributes, position) for attributes, position in xml_records(data[name], local_name))
    keys = [id_key(attributes.get('id')) for _, attributes, _ in author_records]
    counts = Counter(keys)
    referenced = {id_key(attributes.get('authorId')) for _, attributes, _ in comment_records}
    for key in referenced:
        if counts[key] > 1 or key is None and counts[key]:
            shown = key[1] if key else '缺失'
            raise NeedsReview(f'编号“{shown}”被批注正文引用，无法确定作者归属。原文件保留，请人工确认。')
    reserved = {key[1] for key in keys + list(referenced) if valid_id(key)}
    candidate = (max(reserved, default=-1) + 1) & MAX_ID
    seen, changed, remap = set(), {}, {}
    changes = []
    for (part, attributes, position), key in zip(author_records, keys):
        if valid_id(key) and key not in seen:
            seen.add(key)
            continue
        while candidate in reserved:
            candidate = (candidate + 1) & MAX_ID
        number = candidate
        reserved.add(number)
        changed.setdefault(part, []).append((position, 'id', number))
        changes.append(dict(part=part, old=attributes.get('id'), new=number))
        if key is not None and key in referenced:
            remap[key] = number
    comment_updates = 0
    for part, attributes, position in comment_records:
        key = id_key(attributes.get('authorId'))
        if key in remap:
            changed.setdefault(part, []).append((position, 'authorId', remap[key]))
            comment_updates += 1
    patches = {part: replace_attributes(data[part], edits) for part, edits in changed.items()}
    return patches, changes, comment_updates


def repair_file(source, destination):
    source, destination = Path(source), Path(destination)
    before = inspect_file(source)
    record = dict(source=str(source), output='', backup='', mode='copy', status='unchanged', changes=[], comment_updates=0, note='')
    if source.suffix.lower() not in MODERN or before['status'] == 'uncheckable':
        raise NeedsReview(before['note'] or '该文件格式无法自动修复。')
    if before['status'] == 'clear':
        record['note'] = '未发现本次编号问题。'
        return record
    if destination.exists():
        raise FileExistsError(f'输出文件已存在：{destination}')
    with zipfile.ZipFile(source) as archive:
        patches, changes, comment_updates = plan_changes(archive)
        if not changes:
            raise NeedsReview('无法定位需要修改的作者编号。')
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + '.partial')
        # 完整写入并复查后再改为正式扩展名；中断文件保留 .partial，便于识别。
        with partial.open('xb') as stream, zipfile.ZipFile(stream, 'w') as output:
            output.comment = archive.comment
            for info in archive.infolist():
                entry = copy(info)
                if info.filename in patches:
                    output.writestr(entry, patches[info.filename])
                else:
                    with archive.open(info) as reader, output.open(entry, 'w') as writer:
                        shutil.copyfileobj(reader, writer, length=1024 * 1024)
        after = inspect_file(partial)
        if after['status'] != 'clear':
            raise ValueError('输出复查未通过；未生成正式修复版。')
        partial.rename(destination)
    record.update(output=str(destination), status='fixed', changes=changes, comment_updates=comment_updates,
                  note=f'已修复 {len(changes)} 处作者编号，更新 {comment_updates} 处批注引用。')
    return record


def repair_file_in_place(source, backup):
    source, backup = Path(source), Path(backup)
    original = source.stat()
    before = inspect_file(source)
    if before['status'] == 'clear':
        return dict(source=str(source), output='', backup='', mode='in_place', status='unchanged',
                    changes=[], comment_updates=0, note='未发现本次编号问题。', after=before)
    if source.suffix.lower() not in MODERN or before['status'] == 'uncheckable':
        raise NeedsReview(before['note'] or '该文件格式无法自动修复。')
    with zipfile.ZipFile(source) as archive:
        plan_changes(archive)
    backup.parent.mkdir(parents=True, exist_ok=True)
    if backup.exists():
        raise FileExistsError(f'备份文件已存在：{backup}')
    backup_partial = backup.with_name(backup.name + '.partial')
    with source.open('rb') as reader, backup_partial.open('xb') as writer:
        shutil.copyfileobj(reader, writer, length=1024 * 1024)
    shutil.copystat(source, backup_partial)
    backup_partial.rename(backup)
    # 暂存文件与原文件位于同一目录，支持备份目录位于其他磁盘。
    candidate = source.parent / f'.pptrepair-{uuid4().hex}.tmp'
    try:
        record = repair_file(backup, candidate)
        current = source.stat()
        if (current.st_size, current.st_mtime_ns) != (original.st_size, original.st_mtime_ns):
            raise OSError('修复期间原文件发生变化，未写回。')
        read_only = bool(getattr(original, 'st_file_attributes', 0) & 1)
        if read_only:
            source.chmod(original.st_mode | stat.S_IWRITE)
        try:
            os.replace(candidate, source)
        finally:
            if read_only:
                source.chmod(original.st_mode)
        record.update(source=str(source), output=str(source), backup=str(backup), mode='in_place',
                      after=inspect_file(source), note=f'已原位修复 {len(record["changes"])} 处作者编号，原文件已备份。')
        return record
    except Exception:
        # 未写回的内容归入本次备份目录，原文件所在目录不遗留暂存副本。
        for path in [candidate, candidate.with_name(candidate.name + '.partial')]:
            if path.exists():
                suffix = '.partial' if path.name.endswith('.partial') else source.suffix
                retained = backup.parent / f'{source.stem}_未写回修复版{suffix}'
                shutil.move(str(path), str(retained))
        raise


def repair_batch(paths, output_dir, cancelled=None, notify=None, *, in_place=False):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    cancelled = cancelled or threading.Event()
    notify = notify or (lambda **_: None)
    paths = list(dict.fromkeys(map(str, paths)))
    records = []
    summary = dict(started_at=datetime.now().astimezone().isoformat(), state='修复中', total=len(paths),
                   mode='in_place' if in_place else 'copy',
                   counts={key: 0 for key in STATUS}, records=records, output_dir=str(output_dir))
    with (output_dir / '修复清单.csv').open('x', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['原文件', '结果', '修复后文件', '原文件备份', '修复方式', '修改编号数', '更新引用数', '说明'])
        for position, source in enumerate(map(Path, paths), 1):
            if cancelled.is_set():
                break
            destination = output_dir / f'{source.stem}_编号修复版{source.suffix}'
            backup = output_dir / BACKUP_FOLDER / f'{position:04d}' / source.name
            index = 2
            while destination.exists() or destination.with_name(destination.name + '.partial').exists():
                destination = output_dir / f'{source.stem}_编号修复版_{index}{source.suffix}'
                index += 1
            try:
                record = repair_file_in_place(source, backup) if in_place else repair_file(source, destination)
            except NeedsReview as exc:
                record = dict(source=str(source), output='', status='needs_review', changes=[], comment_updates=0, note=str(exc))
            except Exception as exc:
                record = dict(source=str(source), output='', status='failed', changes=[], comment_updates=0, note=f'{type(exc).__name__}: {exc}')
            record.setdefault('mode', 'in_place' if in_place else 'copy')
            record.setdefault('backup', str(backup) if in_place and backup.is_file() else '')
            records.append(record)
            summary['counts'][record['status']] += 1
            writer.writerow([csv_text(value) for value in [record['source'], STATUS[record['status']], record['output'],
                             record['backup'], '直接修复原文件' if in_place else '另存修复版',
                             len(record['changes']), record['comment_updates'], record['note']]])
            stream.flush()
            notify(record=record, done=len(records), total=len(paths), counts=summary['counts'].copy())
    summary.update(state='已停止，保留已完成修复' if cancelled.is_set() else '完成',
                   finished_at=datetime.now().astimezone().isoformat(), processed=len(records))
    (output_dir / '修复记录.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    return summary
