"""两种扫描入口共用的目录筛选与文件发现。"""
import os
from pathlib import Path
import stat


MODES = {'recommended': '推荐扫描', 'full': '全面扫描'}
SKIP_NAMES = {'$recycle.bin', 'system volume information', '.git', 'node_modules',
              '__pycache__', '.venv', 'ppt编号修复备份'}
DEPENDENCY_NAMES = {'site-packages', 'bower_components', '.tox', '.pytest_cache',
                    '.mypy_cache', '.ruff_cache', '.gradle', '.nuget'}
EXTENSIONS = {'.pptx', '.pptm', '.ppsx', '.ppsm', '.potx', '.potm', '.ppt', '.pps', '.pot'}


def path_key(path):
    return os.path.normcase(os.path.abspath(path))


def recommended_paths(roots):
    paths = {}
    for root in roots:
        anchor = Path(root).absolute().anchor
        for name in ('Program Files', 'Program Files (x86)', 'WindowsApps'):
            paths[path_key(os.path.join(anchor, name))] = '程序安装目录'
    local = os.environ.get('LOCALAPPDATA')
    if local:
        for relative, reason in [('Programs', '用户程序安装目录'),
                                 ('uv/cache', 'uv 下载与依赖缓存'),
                                 ('pip/Cache', 'pip 下载缓存'),
                                 ('npm-cache', 'npm 下载缓存')]:
            paths[path_key(Path(local) / relative)] = reason
    program_data = os.environ.get('ProgramData')
    if program_data:
        paths[path_key(Path(program_data) / 'Package Cache')] = '安装包缓存'
    return paths


def recommended_reason(path, paths):
    key = os.path.normcase(path)
    if key in paths:
        return paths[key]
    name = os.path.basename(key).lower()
    if name in DEPENDENCY_NAMES:
        return '开发依赖或工具缓存'
    if name == 'steamlibrary' and os.path.isdir(os.path.join(path, 'steamapps')):
        return 'Steam 游戏库'
    if name == 'steamapps' and os.path.isfile(os.path.join(path, 'libraryfolders.vdf')):
        return 'Steam 游戏安装目录'
    return None


def discover_files(roots, record_skip, cancelled, progress, basic_paths,
                   mode='recommended', exclude_dirs=(), explicit_roots=()):
    if mode not in MODES:
        raise ValueError(f'未知扫描模式：{mode}')
    roots = [os.path.abspath(root) for root in roots]
    custom = {path_key(path) for path in exclude_dirs}
    explicit = {path_key(path) for path in explicit_roots}
    recommended = recommended_paths(roots) if mode == 'recommended' else {}
    basic = {path_key(path) for path in basic_paths}
    seen = set()

    def custom_reason(key):
        if any(key == folder or key.startswith(folder.rstrip(os.sep) + os.sep) for folder in custom):
            return '自定义排除目录'
        return None

    def exclusion(path, bypass):
        key = os.path.normcase(path)
        if os.path.basename(path).lower() in SKIP_NAMES or key in basic:
            return '基础排除目录（系统、回收站、开发依赖或工具备份/测试材料）'
        reason = custom_reason(key)
        if reason:
            return reason
        if mode == 'recommended' and not bypass:
            reason = recommended_reason(path, recommended)
            if reason:
                return '推荐排除：' + reason
        return None

    # 指定目录先检查，整盘扫描随后去重；自动排除不会挡住指定位置。
    roots.sort(key=lambda path: (path_key(path) not in explicit, -len(path)))
    for root in roots:
        bypass = False
        if path_key(root) in explicit and mode == 'recommended':
            current = root
            while current:
                if recommended_reason(current, recommended):
                    bypass = True
                    break
                parent = os.path.dirname(current)
                if parent == current:
                    break
                current = parent
        stack = [(root, None)]
        while stack and not cancelled.is_set():
            path, entry = stack.pop()
            key = os.path.normcase(path)
            if key in seen:
                continue
            try:
                info = entry.stat(follow_symlinks=False) if entry is not None else os.lstat(path)
                attributes = getattr(info, 'st_file_attributes', 0)
                if attributes & (0x1000 | 0x40000 | 0x400000):
                    record_skip(path, '云端占位或离线项目')
                    continue
                if stat.S_ISLNK(info.st_mode) or attributes & 0x400:
                    record_skip(path, '链接或重解析点')
                    continue
                if stat.S_ISDIR(info.st_mode):
                    reason = exclusion(path, bypass) if entry is None else None
                    if reason:
                        record_skip(path, reason)
                        continue
                    seen.add(key)
                    progress(directory=path)
                    with os.scandir(path) as entries:
                        for child in entries:
                            if cancelled.is_set():
                                break
                            if child.name.startswith('~$'):
                                continue
                            if child.is_symlink():
                                record_skip(child.path, '链接或重解析点')
                                continue
                            if child.is_dir(follow_symlinks=False):
                                reason = exclusion(child.path, bypass)
                                if reason:
                                    record_skip(child.path, reason)
                                else:
                                    stack.append((child.path, child))
                            elif os.path.splitext(child.name)[1].lower() in EXTENSIONS:
                                stack.append((child.path, child))
                elif os.path.splitext(path)[1].lower() in EXTENSIONS:
                    reason = custom_reason(key)
                    if reason:
                        record_skip(path, reason)
                        continue
                    seen.add(key)
                    yield Path(path)
            except OSError as exc:
                record_skip(path, f'无法访问：{exc}')
