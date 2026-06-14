# P5.12 Plugin 打包与分发 — 设计文档

日期：2026-06-13  
状态：阶段二（实现完成）

## 包结构

```
my-bundle/
  plugin.json          # 或 .archer-plugin/plugin.json
  skills/
    hello_world.py
  modes/
    demo_mode.md
  hooks.json           # 可选；也可写在 plugin.json 的 hooks 字段
```

## `plugin.json` schema

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | ✓ | 插件 id（`[a-z0-9_-]+`） |
| `version` | ✓ | semver 字符串 |
| `description` | | 简介 |
| `skills` | | 相对路径列表，默认 `skills/*.py` |
| `modes` | | 相对路径列表，默认 `modes/*.md` |
| `hooks` | | 与 `archer.toml [hooks]` 相同结构 |

## 安装位置

`plugins/<name>/`（项目根，已 gitignore）+ `plugins/installed.json` 注册表。

## CLI

- `/plugin install <目录路径>` — 校验、冲突检测、复制安装
- `/plugin install <path.zip>` — 解压后安装
- `/plugin install <https://…/bundle.zip>` — 下载 zip 后安装（上限 20MB）
- `/plugin list` — 已安装插件与 bundled skills/modes 数量
- `/plugin remove <name>` — 卸载

## 集成

- `skills/loader.register_all_skills()` 扫描已安装插件的 `skills/`
- `core/stance.available_modes()` 包含插件 `modes/`
- `core/context._get_mode_prompt()` 可读插件 mode 文件
- `HookRegistry.from_config()` 合并插件 hooks

## 冲突

安装前检测：插件 id 重复、skill 名与内置/其他插件冲突。

## 验收

- [x] `tests/test_plugin.py`
