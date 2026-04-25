"""
@ 文件引用解析器。

用法：
  在输入中写 @/绝对路径 或 @~/相对路径
  支持文本文件（直接注入内容）和图片（base64 → vision API）

示例：
  @~/Desktop/screenshot.png 帮我分析这张截图
  @/Users/Yivxer/Projects/Archer/archer.py 解释一下这段代码
  @~/notes.md 把这篇笔记总结一下
"""
import re
import base64
from pathlib import Path

# 匹配 @ 后跟路径（支持中文、空格用引号包裹）
_REF_PLAIN  = re.compile(r'@([~/\w.\-][\w./\-一-鿿@]*)')
_REF_QUOTED = re.compile(r'@"([^"]+)"')

IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.heic', '.heif'}

_MIME = {
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.png': 'image/png',  '.gif': 'image/gif',
    '.webp': 'image/webp', '.bmp': 'image/bmp',
}

def _resolve(raw: str) -> Path | None:
    p = Path(raw).expanduser()
    if p.exists():
        return p
    return None

def parse_refs(text: str) -> tuple[str, list[dict]]:
    """
    扫描输入中的 @路径，读取内容。
    返回：(清理后的文本，附件列表)

    附件格式：
      文本 → {'type':'text',  'name':str, 'path':str, 'content':str}
      图片 → {'type':'image', 'name':str, 'path':str, 'data':str, 'mime':str}
    """
    refs    = []
    cleaned = text
    seen    = set()

    matches = list(_REF_QUOTED.finditer(text)) + list(_REF_PLAIN.finditer(text))
    matches.sort(key=lambda m: m.start())

    for m in matches:
        raw  = m.group(1).strip()
        path = _resolve(raw)
        if not path or str(path) in seen:
            continue
        seen.add(str(path))

        ext = path.suffix.lower()
        ref: dict = {'name': path.name, 'path': str(path)}

        if ext in IMAGE_EXTS:
            try:
                data = base64.b64encode(path.read_bytes()).decode()
                ref.update({'type': 'image', 'data': data,
                            'mime': _MIME.get(ext, 'image/png')})
                refs.append(ref)
            except Exception as e:
                refs.append({'type': 'error', 'name': path.name,
                             'path': str(path), 'error': str(e)})
        else:
            try:
                content = path.read_text(encoding='utf-8', errors='ignore')
                if len(content) > 8000:
                    content = content[:8000] + f'\n…（已截断，共 {len(content)} 字符）'
                ref.update({'type': 'text', 'content': content})
                refs.append(ref)
            except Exception as e:
                refs.append({'type': 'error', 'name': path.name,
                             'path': str(path), 'error': str(e)})

        cleaned = cleaned.replace(m.group(0), f'[{path.name}]', 1)

    return cleaned, refs

def build_user_content(text: str, refs: list[dict]) -> str | list:
    """
    把文本和附件组合成 API content 格式。
    - 无图片 → 普通字符串（text + 文本附件内嵌）
    - 有图片 → multimodal 列表（vision API 格式）
    """
    text_parts = []
    image_refs = []
    error_refs = []

    for r in refs:
        if r['type'] == 'text':
            text_parts.append(
                f'\n\n[附件：{r["name"]}]\n```\n{r["content"]}\n```'
            )
        elif r['type'] == 'image':
            image_refs.append(r)
        elif r['type'] == 'error':
            error_refs.append(r)

    if error_refs:
        text += '\n\n' + '\n'.join(
            f'[无法读取 {r["name"]}：{r["error"]}]' for r in error_refs
        )

    full_text = text + ''.join(text_parts)

    if not image_refs:
        return full_text

    # 有图片 → multimodal 格式
    content: list = [{'type': 'text', 'text': full_text}]
    for r in image_refs:
        content.append({
            'type': 'image_url',
            'image_url': {'url': f'data:{r["mime"]};base64,{r["data"]}'},
        })
    return content

def ref_summary(refs: list[dict]) -> str:
    """生成附件摘要行，显示在输入框下方。"""
    if not refs:
        return ''
    parts = []
    for r in refs:
        icon = '🖼' if r['type'] == 'image' else ('⚠' if r['type'] == 'error' else '📄')
        parts.append(f'{icon} {r["name"]}')
    return '  '.join(parts)
