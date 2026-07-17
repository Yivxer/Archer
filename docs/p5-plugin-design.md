# P5.12 Plugin 打包与分发 — 设计文档

日期：2026-06-13  
状态：Part 10 评估完成；维持受控 bundle 生命周期，不扩为泛平台

## 包结构

```
my-bundle/
  plugin.json          # 或 .archer-plugin/plugin.json
  skills/
    hello_world.py
  modes/
    demo_mode.md
  experts/
    demo_expert.toml
  hooks.json           # 可选；也可写在 plugin.json 的 hooks 字段
```

## `plugin.json` schema

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | ✓ | 插件 id（`[a-z0-9_-]+`） |
| `version` | ✓ | semver 字符串 |
| `description` | | 简介 |
| `risk` | ✓ | `low` / `medium` / `high` / `critical` |
| `auto_trigger` | ✓ | 是否允许自动触发；boolean |
| `permissions` | ✓ | 权限标识数组，可为空 |
| `inputs` | ✓ | 输入 JSON schema object |
| `outputs` | ✓ | 输出 JSON schema object |
| `skills` | | 相对路径列表，默认 `skills/*.py` |
| `modes` | | 相对路径列表，默认 `modes/*.md` |
| `experts` | | 相对路径列表，默认 `experts/*.toml` |
| `hooks` | | 与 `archer.toml [hooks]` 相同结构 |

## 安装位置

`plugins/<name>/`（项目根，已 gitignore）+ `plugins/installed.json` 注册表。

## CLI

- `/plugin install <目录路径>` — 校验、冲突检测、复制安装
- `/plugin install <path.zip>` — 解压后安装
- `/plugin install <https://…/bundle.zip>` — 下载 zip 后安装（上限 20MB）
- `/plugin list` — 已安装插件与 bundled skills/modes 数量
- `/plugin enable <name>` / `/plugin disable <name>` — 显式控制运行时加载
- `/plugin remove <name>` — 卸载

## 集成

- `skills/loader.register_all_skills()` 扫描已安装插件的 `skills/`
- `core/stance.available_modes()` 包含插件 `modes/`
- `core/experts.load_plugin_experts()` 包含插件 `experts/*.toml`
- `core/context._get_mode_prompt()` 可读插件 mode 文件
- `HookRegistry.from_config()` 合并插件 hooks

## 冲突

安装前检测：manifest 必填契约、插件 id 重复、skill 名与内置/其他插件冲突。安装与卸载采用临时目录、原子注册表写入和失败回滚，禁用插件不会进入 skills、modes 或 hooks 运行时。

## Part 10 评估结论

- Workflow SDK 暂缓；只有至少两个生产 workflow 出现相同生命周期、审批和 receipt 模板时再抽取。
- Plugin 生命周期维持安装、冲突检查、启用、禁用、卸载和失败回滚，不建设 marketplace、远程 registry 或通用编排平台。

## 验收

- [x] `tests/test_plugin.py`
