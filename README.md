# PPT 批注编号检查工具

<img src="assets/app-icon.png" width="88" alt="PPT 批注编号检查工具图标">

Windows 本地演示文件检查与修复工具，可定位传统批注作者编号的重复、缺失、非法值和超范围问题，生成离线报告，并按需另存修复或备份后原位修复。

**当前版本：v1.7 · 扫描优化版**

[下载 Windows 64 位便携版](https://github.com/Tantallium/ppt-comment-audit/releases/tag/v1.7) · [使用说明](使用说明.md) · [MIT 许可证](LICENSE)

## 使用

完整解压便携包，双击 `PPT批注编号检查工具_v1.7.exe`，保留同目录的 `_internal` 文件夹。无需安装 Python、PowerPoint 或 WPS。

1. 选择磁盘或指定文件夹，选择推荐扫描或全面扫描；可添加不扫描的文件夹。
2. 点击“开始检查”，完成后筛选结果、查看详情或打开离线报告。
3. 对编号问题选择另存修复，或选择先备份再直接修复原文件。

所有处理在本机完成，不上传演示文件。另存模式保留原文件，原位模式先备份并复查后写回。批注作者归属不明确时会提示人工确认。

## 功能

- 支持 PPTX、PPTM、PPSX、PPSM、POTX、POTM；旧 PPT、PPS、POT 单独列出。
- 推荐扫描跳过已识别的程序目录、游戏库和缓存；全面扫描保留基础排除规则。
- 自定义排除目录和扫描模式自动保存；手动指定目录可覆盖推荐排除规则。
- 检查结果支持搜索、筛选、批量修复及历史报告读取，报告列出排除原因。
- 输出 HTML、CSV、Markdown 和 JSON 明细；支持停止并保存、关闭前保存。
- Material Design 3 风格界面，支持键盘操作和窗口自适应布局。

同一台电脑、同一批磁盘的对比中，v1.6 扫描耗时 46.49 秒，v1.7 全面扫描耗时 25.78 秒、推荐扫描耗时 17.96 秒；实际速度取决于设备、文件和扫描范围。

## 源码运行

图形界面面向 Windows，使用 Python 3.10 或更新版本。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-ui.txt
.\.venv\Scripts\python.exe -X utf8 ppt_audit.py
```

也可双击 `启动检查.cmd`。命令行用法和修复说明见[使用说明](使用说明.md)。

## 构建与测试

```powershell
.\.venv\Scripts\python.exe -m pip install -r 便携版打包/requirements-build.txt
.\.venv\Scripts\python.exe -m PyInstaller --distpath dist --workpath build 便携版打包/构建配置/PPT批注编号检查工具_v1.7.spec
.\.venv\Scripts\python.exe -X utf8 -m unittest -v test_ppt_audit test_number_repair test_in_place_repair
.\.venv\Scripts\python.exe -X utf8 test_scan_speed.py
```

测试使用合成样本。`test_portable_v17.py` 可验证便携程序的内嵌源码、独立启动、扫描与修复，参数说明可通过 `--help` 查看。

## 已知范围

- 修复范围为传统批注作者编号，不处理加密文件、旧二进制格式、损坏压缩包或其他演示内容故障。
- 当前便携版未进行受信任的数字签名，Windows 可能显示“发布者未知”或 SmartScreen 提示。

## 许可

本项目采用 [MIT 许可证](LICENSE)，版权所有者 Andyzz。第三方组件许可证见[第三方声明](THIRD_PARTY_NOTICES.md)。界面设计参考 [Google Material Design 3](https://m3.material.io/)。
