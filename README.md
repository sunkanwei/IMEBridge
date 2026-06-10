<div align="center">

# IMEBridge

让 Blender 的文本编辑体验真正支持 Windows 中文输入法。

[![Blender](https://img.shields.io/badge/Blender-5.0--5.2-E87D0D?style=for-the-badge&logo=blender&logoColor=white)](https://www.blender.org/)
[![Platform](https://img.shields.io/badge/Windows-x64-0078D4?style=for-the-badge&logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![License](https://img.shields.io/badge/License-GPL--3.0--or--later-2E7D32?style=for-the-badge)](https://www.gnu.org/licenses/gpl-3.0.html)

适用于 Blender 文本编辑器和 3D 文字编辑模式的 Windows IME 桥接扩展。

[个人主页](https://space.bilibili.com/28036907) · [架构说明](./ARCHITECTURE.md)

</div>

## 它解决什么问题

Blender 的部分文本编辑场景对 Windows 中文输入法并不友好，尤其是在文本编辑器和 3D 文字编辑模式里，候选框位置、确认输入、快捷键状态容易出现割裂。

IMEBridge 在 Blender 与 Windows IME 之间建立一层轻量桥接，让中文输入更接近日常桌面软件里的体验：候选框跟随文本位置、确认文本稳定写入、快捷键区域自动回到直接输入状态。

## 功能亮点

| 能力 | 说明 |
| --- | --- |
| 文本编辑器输入 | 支持 Blender Text Editor 中的中文输入、提交和光标位置处理 |
| 3D 文字编辑 | 支持 3D Text edit mode 中直接输入中文 |
| 候选框定位 | 将 IME 候选框移动到更接近当前文本光标的位置 |
| 快捷键保护 | 在快捷键密集的编辑区域临时关闭插件控制的 IME 状态 |
| 自动启用 | 扩展启用后自动挂接当前 Blender 窗口，无需手动按钮 |
| 安全回退 | 非 Windows 或后台环境下保持无操作，避免影响 Blender 启动 |

## 兼容范围

| 项目 | 支持情况 |
| --- | --- |
| Blender | 5.0.x、5.1.x、5.2.x |
| 系统 | Windows x64 |
| 扩展格式 | Blender Extension |
| 输入法 | 使用 Windows IME / IMM32 的中文输入法 |

## 安装方式

1. 下载发布页中的 `IMEBridge-版本号.zip`。
2. 打开 Blender，进入 `Edit > Preferences > Extensions`。
3. 使用 `Install from Disk` 选择 zip 文件。
4. 启用 `IMEBridge`。
5. 打开 Text Editor 或进入 3D Text edit mode，切换中文输入法开始输入。

## 可调设置

在 Blender 的扩展偏好设置中可以调整：

- 显示语言
- 候选框 X / Y 偏移
- 是否在输入开始前预定位候选框
- 是否使用输入法请求的字符偏移
- 是否在快捷键区域自动切换为英文输入状态

默认配置偏向“安装后直接可用”。如果候选框在不同缩放比例、显示器或输入法下略有偏移，可以优先调整 X / Y 偏移。

## 设计边界

IMEBridge 只处理明确支持的 Blender 文本目标：

- Text Editor
- 3D Text edit mode

它不会猜测或接管 Blender 原生 UI 输入框，也不会主动修改用户文件、安装依赖、联网下载内容或写入扩展安装目录。

## 开发结构

```text
IMEBridge/
├─ blender_manifest.toml
├─ __init__.py
├─ bridge/       # 窗口挂钩、IME 消息路由和输入状态切换
├─ core/         # 运行时状态、数据模型和安全清理
├─ preferences/  # 扩展偏好设置与界面文本
├─ targets/      # Blender 文本目标识别与文本写入
└─ win32/        # Win32 / IMM32 ctypes 绑定
```

更完整的内部流程见 [ARCHITECTURE.md](./ARCHITECTURE.md)。

## 打包说明

`README.md` 只用于 GitHub 项目首页展示，不会打进 Blender Extension 发布包。

发布包内容由 `blender_manifest.toml` 的 `[build].paths` 白名单控制；构建时只包含运行扩展所需的 Python 模块、Manifest 和架构说明，避免把展示文档、本地 Git 仓库、缓存文件或临时文件带入最终 zip。

常用验证命令：

```powershell
blender --factory-startup --command extension validate path\to\IMEBridge
blender --factory-startup --command extension build --source-dir path\to\IMEBridge
```

Windows 下也可以直接双击 `build_extension.bat`，它会调用 Blender 官方构建命令，把 `IMEBridge-版本号.zip` 输出到桌面，并检查发布包没有包含 README、bat 或 Python 缓存文件。

macOS 下可以在终端或 Finder 中运行 `build_extension.command`。如果首次复制后 Finder 提示没有执行权限，先运行 `chmod +x build_extension.command`；如果 Blender 没有安装在 `/Applications/Blender.app`，可以先设置 `BLENDER_EXE` 指向 Blender 可执行文件。

## 许可证

IMEBridge 以 `GPL-3.0-or-later` 许可发布。使用、修改和分发时请遵守对应开源许可证要求。
