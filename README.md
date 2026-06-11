<div align="center">

# ⌨️ IMEBridge (输入法桥接助手)

**为 Blender 打造的原生中文输入体验，让汉字键入如丝般顺滑。**

[![Blender Version](https://img.shields.io/badge/Blender-5.0%20%7C%205.1%20%7C%205.2-orange?style=flat-squared&logo=blender&logoColor=white)](https://www.blender.org/)
[![Platform Support](https://img.shields.io/badge/平台-Windows%20x64%20%7C%20macOS%20arm64-blue?style=flat-squared)](https://www.blender.org/)
[![License](https://img.shields.io/badge/协议-GPL%203.0-green?style=flat-squared)](https://www.gnu.org/licenses/gpl-3.0.html)

[✨ 核心功能](#-核心功能) · [💻 兼容范围](#-兼容范围) · [🚀 安装使用](#-安装与使用) · [⚙️ 个性化设置](#-个性化设置)

</div>

---

## 💡 为什么需要 IMEBridge？

在 Blender 中进行文本编辑（例如使用**文本编辑器**编写 Python 脚本，或在 **3D 视图中编辑 3D 文字**）时，输入中文一直是一个痛点：
* ❌ **无法唤起输入法**：常常只能强行输入英文字符，或者输入法候选框无法正常呼出。
* ❌ **候选框位置错乱**：输入法候选框经常遗留在屏幕角落，视线需要频繁来回移动。
* ❌ **快捷键状态冲突**：输入完中文后，由于没有自动切回英文状态，导致 Blender 的各种快捷键失效或误触。

**IMEBridge** 在 Blender 和系统原生输入法（IME）之间建立起了一座轻量级的桥梁。它不需要你改变打字习惯，安装后即可直接在 Blender 内部顺畅、自然地使用系统输入法输入中文。

---

## ✨ 核心功能

### 🎯 候选框智能跟随 (Candidate Follow)
输入法的候选字窗口会实时、精准地定位在您当前的文本光标下方。打字时视线无需离开编辑区域，体验媲美专业的文本编辑器。

### 🛡️ 快捷键自动避让 (Smart Hotkey Protection)
当您的鼠标离开文本编辑区，点击 3D 视图等依赖快捷键的操作区域时，插件会自动将当前窗口的输入法状态临时切换为英文，确保 Blender 的原生快捷键免受中文输入法干扰；而当您重新回到文本编辑区时，又会自动恢复您的输入状态。

### ⚡ 无感自动启用 (Seamless Integration)
插件启用后，会自动挂接当前的 Blender 窗口并开始工作。无需手动点击任何“激活”按钮，一切都在后台默默完成。

### 📝 多场景深度支持 (Rich Editing Modes)
* **Text Editor (文本编辑器)**：支持编写中文注释、字符串，完美处理回车提交与光标定位。
* **3D Text Edit (3D 文字编辑模式)**：支持在 3D 视图中直接呼出输入法，为 3D 艺术字体、排版直接键入中文。

---

## 💻 兼容范围

| 项目 | 支持范围 | 备注 |
| :--- | :--- | :--- |
| **Blender 版本** | `5.0.x`、`5.1.x`、`5.2.x` | 适配最新的 Blender 插件扩展标准 |
| **操作系统** | Windows x64、macOS arm64 (Apple Silicon) | 深度对接系统底层 API |
| **输入法支持** | 已验证：微软拼音、macOS 系统输入法 | 设计上兼容遵循系统标准接口的输入法；搜狗、百度、Rime 等需按发布门禁逐项确认 |

---

## 🚀 安装与使用

1. **获取发布包**：下载最新版本的 `IMEBridge-x.x.x.zip` 发布文件。
2. **安装插件**：
   * 打开 Blender，依次点击菜单栏 `Edit (编辑) > Preferences (偏好设置) > Extensions (扩展)`。
   * 点击右上角的箭头菜单，选择 `Install from Disk (从磁盘安装)`，选中下载的 `.zip` 文件。
3. **启用并打字**：
   * 勾选启用 `IMEBridge`。
   * 打开 Blender 文本编辑器，或者在 3D 视图中添加文本并按 `Tab` 进入编辑模式，切换中文输入法，即可开始顺畅打字！

---

## ⚙️ 个性化设置

在 Blender 的插件偏好设置中，您可以根据屏幕缩放、使用习惯调整以下参数：

* **显示语言 (Language)**：支持简体中文、繁体中文、英文、日语、韩语等界面语言。
* **候选框位置偏移 (X/Y Offset)**：若因显示器缩放、分辨率或特定输入法皮肤导致候选框定位不准，可微调 X/Y 轴像素偏移量。
* **提前定位候选框 (Pre-position)**：在打字前就预先锁定输入法候选窗口位置，避免首字输入时窗口闪烁。
* **叠加组合字符偏移 (Composition Offset)**：使用输入法反馈的内部字符长度进行更精细的位移定位。
* **快捷键区域自动英文**：开启后，鼠标移至快捷键密集区时自动闭合中文输入状态，防止快捷键误触。

---

## 📄 开源协议

本插件采用 [GPL-3.0-or-later](https://www.gnu.org/licenses/gpl-3.0.html) 开源许可协议发布。您可以自由地使用、修改和分发。
