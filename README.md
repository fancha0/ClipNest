# ClipNest

现代化 Windows 剪贴板管理工具：自动记录剪贴板历史，标签页分组管理，全局快捷键呼出，回车即粘贴。支持应用内一键自动更新。

项目地址：<https://github.com/fancha0/ClipNest>

ClipNest 适合需要频繁复制、整理和重复粘贴内容的场景。所有剪贴板数据默认保存在本机，不上传到云端。

## ✨ 功能特性

- 📋 **剪贴板历史** — 自动记录文本、图片、文件、富文本、图文等内容
- 🗂 **标签页分类** — 常用语、代码、地址、账号等分组管理
- ⚡ **快速粘贴** — 全局快捷键呼出，按数字键 1-9 或方向键选择，回车直接粘贴到目标窗口
- 🔍 **全局搜索** — Ctrl+F 秒搜全部条目
- 📌 **置顶与备注** — 重要条目置顶，备注支持自定义颜色与字号
- 🎨 **主题** — 浅色 / 深色 / 跟随系统，Windows 11 风格设置界面
- 🔄 **应用内自动更新** — 检查更新 → 下载 → 自动安装并重启，全程一键
- 💾 **数据管理** — SQLite 本地存储，支持打包导出 / 导入（.fluxpkg），换机无忧
- 🖥 **系统托盘** — 常驻后台，随用随呼
- 🧩 **来源识别** — 条目可显示捕获来源应用，方便排查重复内容

## 📦 安装

**方式一：安装包（推荐）**

1. 从 [Releases](https://github.com/fancha0/ClipNest/releases/latest) 下载 `ClipNest-Setup.exe`
2. 双击运行，一路下一步即可（免管理员权限，安装到当前用户目录）
3. 安装后开始菜单出现 ClipNest，控制面板/设置中可随时卸载

**方式二：便携版**

1. 下载 `ClipNest-Windows.zip`，解压到任意目录（无需安装）
2. 运行 `ClipNest.exe`

> 首次运行时 Windows SmartScreen 可能提示「未知发布者」，点击「更多信息」→「仍要运行」即可。

## ⌨️ 快捷键

| 快捷键 | 功能 |
| --- | --- |
| `Ctrl+Shift+V`（默认，可自定义） | 呼出 / 隐藏主窗口 |
| `Ctrl+F` | 聚焦搜索框 |
| `Ctrl+N` | 新建条目 |
| `1` ~ `9` | 直接粘贴列表第 N 条 |
| `Enter` | 粘贴当前选中条目 |
| `Esc` | 清除搜索 / 返回列表 |

全局快捷键可在「设置 → 通用」中自定义（至少需要一个修饰键）。

## 🔄 自动更新

「设置 → 关于」中点击**检查更新**，或开启**启动时自动检查**（默认开启）：发现新版本时自动弹出更新窗口，一键下载、自动安装并重启。

更新包优先从 ClipNest 自有更新服务器下载，GitHub Releases 作为备用来源。更新过程会校验安装包完整性，下载完成后自动替换并重启。

## ❓ 常见问题

**数据存储在哪里？会联网吗？**
数据保存在本机 `%APPDATA%\ClipNest\clipboard.db`（从旧版升级的用户在 `%APPDATA%\CrossClipboard\`）。纯本地 SQLite 存储，除检查更新外不进行任何网络传输。

**杀毒软件提示风险？**
个人开发者应用未购买代码签名证书，可能被部分杀毒软件误报。将 ClipNest 所在目录加入信任区即可。

**快捷键没有反应？**
多半是被其他软件占用了（例如 `Win+V` 是 Windows 自带的剪贴板历史）。请在「设置 → 通用」中更换快捷键。

**如何排查异常？**
日志文件位于数据目录下的 `clipnest.log`。反馈问题时请附上相关日志片段。

**如何关闭诊断日志？**
在「设置 → 关于 → 诊断日志」中关闭即可。高级用户也可以设置环境变量 `CLIPNEST_DIAGNOSTIC_LOG=0` 后重启软件。

**如何迁移到新电脑？**
旧电脑进入「设置 → 数据 → 导出」，得到 `.fluxpkg` 数据包；新电脑安装 ClipNest 后，在同一位置选择「导入」即可。

## 🛠 开发

- 技术栈：Python 3.13 + PySide6 + SQLite

```powershell
# 运行（开发模式）
python main.py

# 运行测试
python -m unittest discover -s tests

# 打包 exe
.\scripts\build_windows.ps1
```

- 代码结构：`clipboard_manager/` 下分为 `ui`（界面）、`services`（剪贴板/热键/粘贴/更新服务）、`controller`（业务协调）、`repository`（数据层）
- 一键发版：`.\scripts\release.ps1`（打包 + 上传更新服务器 + GitHub Release）

### 项目结构

```text
clipboard_manager/
├── controller.py       # 业务协调
├── repository.py       # SQLite 数据层
├── services/           # 剪贴板、热键、粘贴、更新服务
└── ui/                 # 主窗口、设置、条目绘制和更新界面
tests/                  # 单元测试
installer/              # Inno Setup 安装包脚本
scripts/                # Windows 构建与发布脚本
```

## 📄 许可

本项目暂未选择开源许可证，代码仅供学习与个人使用。
