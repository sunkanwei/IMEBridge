# IMEBridge 测试与门禁

这个目录是 IMEBridge 的长期质量系统。它只守关键风险，不追求堆测试数量。

## 设计原则

- 快速测试守住纯逻辑、状态机和跨模块协作。
- Blender 原生输入、候选框和平台消息只做少量 smoke 与发布前手动门禁。
- 所有测试辅助、检查脚本和发布清单都放在 `tests/` 下，根目录不再增加其他文件夹。
- `tests/` 是仓库质量资产，应该提交到 git。
- `tests/` 不是扩展运行资产，不能进入 Blender 发布包。
- 门禁脚本会同时检查生产源码清单完整性，以及 `tests/` 没有被误加入 manifest 或发布 zip。

## 版本控制与打包边界

`tests/` 跟随源码一起维护，用来防止回归、说明发布门禁、保存可复用的 fake 环境。
发布 zip 只面向最终用户安装，应该只包含 `blender_manifest.toml` 的 `[build].paths`
列出的扩展运行文件。

因此正确状态是：

- git 仓库包含 `tests/`。
- `blender_manifest.toml` 不包含 `tests/`。
- 构建出来的 zip 不包含 `tests/`、缓存、构建入口脚本或本地文件。

## 推荐命令

```powershell
python tests/run.py quick
python tests/run.py full
python tests/run.py release --package C:\path\to\IMEBridge-0.2.0.zip
```

`quick` 适合日常提交前运行：

- 编译扩展源码和测试源码。
- 运行 `unittest` 自动测试。
- 检查 `blender_manifest.toml` 的生产源码清单、失效路径和禁止发布路径。
- 检查文本卫生：尾随空白、合并冲突标记和 Python 制表符缩进。

`full` 在 `quick` 基础上增加 Blender 官方扩展校验和注册/卸载 smoke；如果找不到 Blender，会明确失败。

`release` 在 `full` 基础上检查发布包内容。真实 IME 行为仍需要执行
`tests/manual/release-gate.md`。

## 测试重点

- `bridge/ime_guards.py` 及其 focused guard 模块：确认空格物理序列、Caps Lock 直接 ASCII 输入、预编辑保护。
- `bridge/message_router.py` 及 scope/activation 模块：目标清理、IME 结果入队、Unicode 文本后的 Tab 缩进。
- `targets/text.py` 及其 focused Text 模块：Text Editor 事务、选区替换、Unicode 光标判断。
- `bridge/font_commit.py`：3D Text 兜底提交、双路提交去重。
- `bridge/ime_switch.py`：只恢复 IMEBridge 自己关闭过的窗口 IME 状态。
- `blender_manifest.toml` 和发布 zip：生产源码清单完整，测试和本地文件不进入发布包。
