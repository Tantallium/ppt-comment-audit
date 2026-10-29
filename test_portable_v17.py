"""验证 v1.7 文件夹便携成品及其内嵌源码、扫描模式与修复行为。"""
import argparse
import json
import marshal
import os
from pathlib import Path
import shutil
import stat
import subprocess
import types

from PyInstaller.archive.readers import CArchiveReader

import ppt_audit
from test_number_repair import RepairTests


BASE = Path(__file__).resolve().parent


def normalized(code):
    return code.replace(co_filename='<source>', co_consts=tuple(
        normalized(item) if isinstance(item, types.CodeType) else item for item in code.co_consts))


def verify(exe, work, result_path):
    work.mkdir(parents=True, exist_ok=False)
    package = CArchiveReader(str(exe))
    pyz = package.open_embedded_archive('PYZ.pyz')
    embedded_sources = {'ppt_audit': BASE / '便携版打包/源码/ppt_audit.py',
                        **{name: BASE / f'{name}.py' for name in ('md3_ui', 'scan_paths', 'ppt_report', 'ppt_repair')}}
    for name, path in embedded_sources.items():
        embedded = marshal.loads(package.extract(name)) if name == 'ppt_audit' else pyz.extract(name)
        expected = compile(path.read_text(encoding='utf-8-sig'), str(path), 'exec')
        assert normalized(embedded) == normalized(expected), name
    assert not any(path.suffix.lower() in ppt_audit.MODERN | ppt_audit.LEGACY | {'.jsonl'}
                   for path in exe.parent.rglob('*') if path.is_file())
    print('内嵌的五个模块与当前源码一致', flush=True)

    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(('PYTHON', 'TCL', 'TK', '_PYI'))
           and key.upper() not in {'VIRTUAL_ENV', '__PYVENV_LAUNCHER__'}}
    windows = Path(env['SYSTEMROOT'])
    env['PATH'] = os.pathsep.join(map(str, [windows / 'System32', windows]))

    def execute(arguments, environment=None):
        completed = subprocess.run([str(exe), *map(str, arguments)], cwd=exe.parent,
                                   env=environment or env, capture_output=True, timeout=90)
        assert completed.returncode == 0, (arguments, completed.returncode, completed.stderr)

    invalid_temp = work / 'temp-is-a-file.txt'
    invalid_temp.write_text('test', encoding='utf-8')
    for name, environment in [('默认环境', env), ('无效临时目录', dict(env, TMP=str(invalid_temp), TEMP=str(invalid_temp)))]:
        ready = work / f'{name}.json'
        execute(['--verify-gui', ready], environment)
        data = json.loads(ready.read_text(encoding='utf-8'))
        assert data['gui_ready'] and data['frozen']
        assert Path(data['application_directory']) == exe.parent
    print('独立启动和无效临时目录启动通过', flush=True)

    fixture = RepairTests()
    fixture.folder = work / '小型样本'
    fixture.folder.mkdir()
    samples = [fixture.package([0, 1, 1], name='重复编号.pptx'),
               fixture.package([3, 3], comments=[3], name='作者归属待确认.pptx'),
               fixture.package([7, -1], comments=[-1, 7], name='非法编号引用.pptx'),
               fixture.package([0, 1], name='正常文件.pptx')]
    originals = {str(path): path.read_bytes() for path in samples}
    dependency = fixture.folder / '运行环境/site-packages'
    dependency.mkdir(parents=True)
    template = fixture.package([0, 1], name='程序模板.pptx', folder=dependency)
    counts = {}
    for mode, expected_count in [('recommended', 4), ('full', 5)]:
        report = work / mode
        execute([fixture.folder, '--scan-mode', mode, '--output', report])
        summary = json.loads((report / '扫描摘要.json').read_text(encoding='utf-8'))
        assert summary['scan_mode'] == mode and summary['checked'] == expected_count
        rows = [json.loads(line) for line in (report / '逐文件详情.jsonl').read_text(encoding='utf-8').splitlines()]
        for row in rows:
            assert row == ppt_audit.inspect_file(Path(row['path']))
        assert 'v1.7' in (report / '检查报告.html').read_text(encoding='utf-8')
        counts[mode] = summary['counts']
    selected = work / '指定排除目录验证'
    execute([dependency, '--output', selected])
    assert json.loads((selected / '扫描摘要.json').read_text(encoding='utf-8'))['checked'] == 1
    for mode in ('full', 'recommended'):
        report = work / f'自定义排除-{mode}'
        execute([dependency, '--scan-mode', mode, '--exclude-dir', dependency, '--output', report])
        assert json.loads((report / '扫描摘要.json').read_text(encoding='utf-8'))['checked'] == 0
    print('两种扫描模式、指定目录覆盖和自定义排除通过', flush=True)

    copy_output = work / '另存修复'
    execute(['--repair', *samples, '--output', copy_output])
    copy_result = json.loads((copy_output / '修复记录.json').read_text(encoding='utf-8'))
    assert copy_result['counts'] == dict(fixed=2, unchanged=1, needs_review=1, failed=0)
    assert copy_result['mode'] == 'copy'
    for record in copy_result['records']:
        if record['status'] == 'fixed':
            output = Path(record['output'])
            assert ppt_audit.inspect_file(output)['status'] == 'clear'
            fixture.verify_members(Path(record['source']), output, {'ppt/commentAuthors.xml', 'ppt/comments/comment1.xml'})
    assert originals == {str(path): path.read_bytes() for path in samples}

    inplace = work / '原位修复样本'
    inplace.mkdir()
    source = inplace / '原位测试.pptx'
    shutil.copy2(samples[0], source)
    source.chmod(stat.S_IREAD)
    record_folder = inplace / '修复记录'
    execute(['--repair', '--in-place', source, '--output', record_folder])
    inplace_result = json.loads((record_folder / '修复记录.json').read_text(encoding='utf-8'))
    assert inplace_result['counts'] == dict(fixed=1, unchanged=0, needs_review=0, failed=0)
    record = inplace_result['records'][0]
    assert Path(record['backup']).read_bytes() == originals[str(samples[0])]
    assert source.stat().st_file_attributes & 1
    assert ppt_audit.inspect_file(source)['status'] == 'clear'
    fixture.verify_members(samples[0], source, {'ppt/commentAuthors.xml'})
    report = work / '备份排除复查'
    execute([inplace, '--output', report])
    assert json.loads((report / '扫描摘要.json').read_text(encoding='utf-8'))['checked'] == 1
    print('另存修复、原位修复、精确备份和只读属性通过', flush=True)

    result = dict(version='1.7.0.0', executable=str(exe), embedded_modules_match=list(embedded_sources),
                  standalone=True, invalid_temp_start=True, no_user_materials_bundled=True,
                  scan_counts=counts, explicit_folder_override=True, custom_exclusions_both_modes=True,
                  source_samples_unchanged=True, copy_repair_counts=copy_result['counts'],
                  inplace_repair_counts=inplace_result['counts'], exact_backup=True,
                  readonly_preserved=True, backup_excluded=True, other_zip_parts_preserved=True)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', required=True, type=Path)
    parser.add_argument('--work', required=True, type=Path)
    parser.add_argument('--result', required=True, type=Path)
    args = parser.parse_args()
    verify(args.exe.resolve(), args.work.resolve(), args.result.resolve())
