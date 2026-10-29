# Windows 便携版构建

当前版本为 v1.7 扫描优化版，采用目录便携形式。构建配置为 `构建配置/PPT批注编号检查工具_v1.7.spec`。

在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r 便携版打包/requirements-build.txt
.\.venv\Scripts\python.exe -m PyInstaller --distpath dist --workpath build 便携版打包/构建配置/PPT批注编号检查工具_v1.7.spec
```

输出目录为 `dist/PPT批注编号检查工具_v1.7_Windows64位`。保留 EXE 旁的 `_internal` 文件夹；图标与字体已由构建配置加入。分发时附上项目 `LICENSE`、`使用说明.md`、`THIRD_PARTY_NOTICES.md` 和相关运行库许可证。

`源码/ppt_audit.py` 提供便携运行路径，与源码入口共用 `md3_ui.py`、`scan_paths.py`、`ppt_report.py` 和 `ppt_repair.py`。便携验证入口为根目录的 `test_portable_v17.py`，使用合成样本。

当前发布版未进行受信任的数字签名。
