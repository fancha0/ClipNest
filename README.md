# ClipNest 剪贴板管理工具

ClipNest 是一个基于 PySide6 + SQLite 的本地剪贴板管理工具，支持 Windows 和 macOS，用来保存、分类、搜索和快速粘贴常用内容。

## 主要功能

- 实时监听并保存剪贴板文本。
- 支持图片剪贴板内容采集和本地保存。
- 支持富文本、图文、文件、URL 等多种剪贴板内容。
- 支持标签页分类管理，例如常用语、代码、地址、账号等。
- 支持手动新建、编辑、删除、移动条目。
- 支持条目置顶，置顶内容始终显示在当前标签页顶部。
- 支持右键菜单操作，包括编辑、删除、置顶、取消置顶等。
- 点击条目后自动写入剪贴板并粘贴到当前窗口。
- 支持自定义全局快捷键。
- 支持窗口置顶、窗口尺寸和布局记忆。
- 使用 SQLite 本地持久化存储。

## 快速开始

推荐 Python 版本：`3.10 - 3.12`

```bash
pip install -r requirements.txt
python main.py
```

## 默认行为

- 默认标签页：`常用语 / 代码 / 地址 / 账号`
- 每个标签页默认最多保存：`100` 条
- 默认全局快捷键：
  - Windows：`Ctrl+Shift+V`
  - macOS：`Cmd+Shift+V`
- 按一次快捷键打开主窗口，再按一次隐藏到后台托盘。

## 数据说明

- 数据保存在本机 SQLite 数据库中。
- 剪贴板内容不会上传到服务器。
- 如果换电脑使用，需要单独备份本机数据库和配置文件。
- macOS 上使用全局快捷键和模拟粘贴时，可能需要开启辅助功能权限。

## Windows 打包

使用项目自带脚本：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

可选图标：

- 优先放置：`assets\clipnest.ico`
- 或放置：`assets\clipnest.png`，脚本会自动转换为 ico。

输出位置：

- 程序目录：`dist\ClipNest\`
- 可执行文件：`dist\ClipNest\ClipNest.exe`
- 压缩包：`dist\ClipNest.zip`

## macOS 打包

> macOS `.app` 不能在 Windows 上直接构建，需要在 macOS 电脑上运行脚本。

```bash
chmod +x ./scripts/build_macos.sh
./scripts/build_macos.sh
```

输出位置：

- App：`release/macos/ClipNest.app`
- 压缩包：`release/macos/ClipNest_macOS.zip`

可选图标：

- 放置：`assets/clipnest.icns`

## 开发说明

常用检查命令：

```bash
python -m compileall clipboard_manager tests
python -m unittest discover -s tests
```

项目主要目录：

- `clipboard_manager/`：主程序代码
- `clipboard_manager/services/`：剪贴板采集、解析、粘贴等服务
- `clipboard_manager/ui/`：界面相关代码
- `tests/`：单元测试
- `scripts/`：打包脚本
