# Windows 便携版构建

当前版本为 v1.4 文件检查版，采用目录便携形式。构建配置为 `构建配置/PPT批注编号检查工具_v1.4.spec`。

在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r 便携版打包/requirements-build.txt
.\.venv\Scripts\python.exe -m PyInstaller --distpath dist --workpath build 便携版打包/构建配置/PPT批注编号检查工具_v1.4.spec
```

输出目录为 `dist/PPT批注编号检查工具_v1.4_Windows64位`。保留 EXE 旁的 `_internal` 文件夹；图标与字体已由构建配置加入。

分发时附上项目 `LICENSE`、`使用说明.md`、`THIRD_PARTY_NOTICES.md`，以及依赖和运行库的许可证。现有发布包已包含完整的 `运行库许可` 目录。

`源码/ppt_audit.py` 提供便携运行路径；界面和报告分别共用根目录的 `md3_ui.py` 和 `ppt_report.py`。

便携包验证入口为根目录 `test_portable_v14.py`。该脚本使用合成样本，默认不打开图形界面；`--gui` 用于额外验证图形界面启动。

当前发布版未进行受信任代码签名。
