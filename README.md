# PPT 批注编号检查工具

<img src="assets/app-icon.png" width="88" alt="PPT 批注编号检查工具图标">

Windows 本地演示文件检查工具，定位传统批注作者编号的重复、缺失、非法值和超范围问题，并生成可筛选的离线报告。

**当前版本：v1.4 · Material Design 3 界面 · 只读检查**

[下载 Windows 64 位便携版](https://github.com/Tantallium/ppt-comment-audit/releases/tag/v1.4) · [使用说明](使用说明.md) · [MIT 许可证](LICENSE)

## 使用

完整解压便携包，双击 `PPT批注编号检查工具_v1.4.exe`，保留同目录的 `_internal` 文件夹。无需安装 Python、PowerPoint 或 WPS。

1. 选择本地磁盘或添加指定文件夹。
2. 点击“开始检查”，等待完成；也可“停止并保存”保留部分结果。
3. 在“检查结果”中筛选或搜索文件，查看详情和报告。

程序只读取演示文件，报告写入程序旁的 `报告` 目录。所有检查在本机完成，不上传文件。

## 功能

- 支持 PPTX、PPTM、PPSX、PPSM、POTX、POTM；旧 PPT、PPS、POT 单独列出。
- 检查传统批注作者编号，显示重复位置与保存软件标记。
- 磁盘多选、指定文件夹、进度显示、停止保存和关闭前保存。
- 结果筛选、路径搜索、复制路径、打开所在文件夹和历史报告读取。
- 输出 HTML、CSV、Markdown 与 JSON 明细，HTML 报告可离线使用。
- Material Design 3 风格界面；较窄窗口采用上下布局，盘符自动换行。

## 源码运行

图形界面面向 Windows；使用 Python 3.10 或更新版本。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-ui.txt
.\.venv\Scripts\python.exe -X utf8 ppt_audit.py
```

也可双击 `启动检查.cmd`，优先使用项目中的 `.venv`。

命令行检查只需 Python 标准库：

```powershell
python -X utf8 ppt_audit.py 'E:\演示文稿' --output 'E:\检查报告\本次检查'
```

输出目录应为新目录；已有报告不会覆盖。

## 构建与测试

```powershell
.\.venv\Scripts\python.exe -m pip install -r 便携版打包/requirements-build.txt
.\.venv\Scripts\python.exe -m PyInstaller --distpath dist --workpath build 便携版打包/构建配置/PPT批注编号检查工具_v1.4.spec
.\.venv\Scripts\python.exe -X utf8 -m unittest -v test_ppt_audit
```

测试使用合成样本，不依赖私人演示文件。`test_audit_fixes.py` 包含额外检测与保存回归；`test_drive_layout.py`、`test_md3_alignment.py`、`test_md3_ui.py` 用于 Windows 界面检查。

下载发布包后，可验证便携运行与报告：

```powershell
.\.venv\Scripts\python.exe -X utf8 test_portable_v14.py 'ppt-comment-audit-v1.4-windows-x64.zip'
```

该命令默认只运行命令行检查；加 `--gui` 可额外检查图形界面启动。

## 已知范围

- v1.4 不自动修复文件；“未发现本次编号问题”不代表 PowerPoint 一定能打开文件。
- 不处理加密文件、旧二进制格式或其他演示内容故障。
- “打开所在文件夹”依赖 Windows Shell；已报告的 Windows 环境存在拒绝访问问题，尚未修复。可使用“复制路径”后在资源管理器中定位。
- 当前便携版未做受信任的代码签名，Windows 可能显示“发布者未知”或 SmartScreen 提示。

## 许可

本项目采用 [MIT 许可证](LICENSE)，版权所有者 Andyzz。第三方组件各自的许可证继续适用，见 [第三方声明](THIRD_PARTY_NOTICES.md)。

界面设计参考 [Google Material Design 3](https://m3.material.io/)。
