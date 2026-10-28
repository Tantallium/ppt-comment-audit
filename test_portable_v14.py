"""验证完整便携包的独立检查与报告；--gui 可选验证图形界面启动。"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import zipfile

import ppt_audit
import test_ppt_audit as fixtures

BASE = Path(__file__).resolve().parent
RELEASE_NAME = 'PPT批注编号检查工具_v1.4_Windows64位'


def verify(archive_path, gui=False):
    folder = BASE / '验证记录' / ('便携-v1.4-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    folder.mkdir(parents=True)
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.testzip() is None
        excluded = ppt_audit.MODERN | ppt_audit.LEGACY | {'.jsonl'}
        assert not any(Path(name).suffix.lower() in excluded for name in archive.namelist())
        archive.extractall(folder / '中文 空格路径')
    exe = folder / '中文 空格路径' / RELEASE_NAME / 'PPT批注编号检查工具_v1.4.exe'
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(('PYTHON', 'TCL', 'TK', '_PYI'))
           and key.upper() not in {'VIRTUAL_ENV', '__PYVENV_LAUNCHER__'}}
    windows = Path(env['SYSTEMROOT'])
    env['PATH'] = os.pathsep.join(str(p) for p in [windows / 'System32', windows])

    def execute(arguments):
        result = subprocess.run([str(exe), *map(str, arguments)], cwd=exe.parent,
                                env=env, capture_output=True, timeout=40)
        assert result.returncode == 0, (result.returncode, result.stderr)

    invalid = folder / 'temp-is-a-file.txt'
    invalid.write_text('test', encoding='utf-8')
    env['TEMP'] = env['TMP'] = str(invalid)
    if gui:
        ready = folder / '界面启动.json'
        execute(['--verify-gui', ready])
        metadata = json.loads(ready.read_text(encoding='utf-8'))
        assert metadata['gui_ready'] and metadata['frozen']
        assert Path(metadata['application_directory']) == exe.parent

    fixtures.RUN = folder
    fixtures.FIXTURES = folder / '合成样本'
    samples = [fixtures.fixture('正常.pptx', [0, 1]),
               fixtures.fixture('重复编号.pptx', [0, 1, 1]),
               fixtures.fixture('非法编号.pptm', [-1]),
               fixtures.fixture('无批注.ppsx', content='<Types/>')]
    broken = fixtures.FIXTURES / '损坏.pptx'
    broken.write_bytes(b'not a zip archive')
    legacy = fixtures.FIXTURES / '旧格式.ppt'
    legacy.write_bytes(b'legacy format sample')
    samples += [broken, legacy]
    before = {path: path.read_bytes() for path in samples}
    report = folder / '检查报告'
    execute([*samples, '--output', report])
    summary = json.loads((report / '扫描摘要.json').read_text(encoding='utf-8'))
    results = [json.loads(line) for line in (report / '逐文件详情.jsonl').read_text(encoding='utf-8').splitlines()]
    by_path = {row['path']: row for row in results}
    assert summary['state'] == '完成' and summary['checked'] == len(samples)
    for path in samples:
        assert by_path[str(path)] == ppt_audit.inspect_file(path)
        assert before[path] == path.read_bytes()
    assert summary['counts'] == dict(duplicate=1, invalid=1, clear=2, uncheckable=1, unsupported=1)
    assert '<title>PPT 批注编号检查报告</title>' in (report / '检查报告.html').read_text(encoding='utf-8')
    outcome = dict(version='1.4', samples=len(samples), standalone=True, zip_crc=True,
                   invalid_temp_cli=True, chinese_space_path=True, source_files_unchanged=True,
                   gui_checked=gui, counts=summary['counts'], report=str(report))
    (folder / '验证结论.json').write_text(json.dumps(outcome, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(outcome, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', nargs='?', type=Path,
                        default=BASE / 'ppt-comment-audit-v1.4-windows-x64.zip')
    parser.add_argument('--gui', action='store_true', help='额外检查图形界面启动')
    arguments = parser.parse_args()
    verify(arguments.archive.resolve(), arguments.gui)
