"""
image_generator — AI 图片生成

读取与 archer.toml 相同的配置，调用 OpenAI DALL-E API 生成图片。
如果 base_url 是自定义端点（非 OpenAI 官方），尝试调用 /images/generations 端点；
若不支持则提示用户更换 API 端点。

生成结果：默认返回 URL，可选保存为本地 PNG 文件。
"""
import os
import tomllib
from pathlib import Path
from urllib.request import urlretrieve

SKILL = {
    "name": "image_generator",
    "description": "AI 图片生成（DALL-E 兼容 API），返回图片 URL 或保存为本地 PNG",
    "version": "1.0.0",
    "author": "archer-builtin",
    "risk": "low",
    "default_timeout": 60,
}

_CFG_PATH  = Path(__file__).parent.parent / "archer.toml"
_ENV_PATH = Path(__file__).parent.parent / ".env"


def _read_dotenv() -> dict[str, str]:
    values: dict[str, str] = {}
    if not _ENV_PATH.exists():
        return values
    for raw in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def _load_cfg() -> dict:
    env  = _read_dotenv()
    with open(_CFG_PATH, "rb") as f:
        cfg = tomllib.load(f)
    api = cfg.setdefault("api", {})
    api_key = os.environ.get("ARCHER_API_KEY") or env.get("ARCHER_API_KEY")
    base_url = os.environ.get("ARCHER_BASE_URL") or env.get("ARCHER_BASE_URL")
    if api_key:
        api["api_key"] = api_key
    if base_url:
        api["base_url"] = base_url
    return cfg


def _get_client():
    from openai import OpenAI
    cfg = _load_cfg()
    api_key  = cfg["api"]["api_key"]
    base_url = cfg["api"].get("base_url", "https://api.openai.com/v1")
    return OpenAI(api_key=api_key, base_url=base_url), cfg


def _save_image(image_url: str, save_path: str | None) -> str:
    if not save_path:
        return f"图片 URL：{image_url}"
    p = Path(save_path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        urlretrieve(image_url, str(p))
        return f"✅ 图片已保存：{p}\n图片 URL：{image_url}"
    except Exception as e:
        return f"❌ 保存失败：{e}\n图片 URL：{image_url}"


# ── Schema ─────────────────────────────────────────────────────

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "image_generator",
            "description": (
                "AI 生成图片（DALL-E 兼容 API）。"
                "生成的图片以 URL 形式返回，可选保存为本地 PNG 文件。"
                "适合生成博客配图、社交媒体图片、演示文稿插图等。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "图片描述 prompt，尽量具体（风格/主体/背景/色调）",
                    },
                    "size": {
                        "type": "string",
                        "enum": ["256x256", "512x512", "1024x1024",
                                "1792x1024", "1024x1792"],
                        "description": "图片尺寸，默认 1024x1024",
                    },
                    "quality": {
                        "type": "string",
                        "enum": ["standard", "hd"],
                        "description": "图片质量，默认 standard（速度快）；hd 更精细但慢",
                    },
                    "save_path": {
                        "type": "string",
                        "description": "本地保存路径（.png），填写后自动下载图片到本地",
                    },
                    "n": {
                        "type": "integer",
                        "description": "生成数量，默认 1，最多 4",
                    },
                },
                "required": ["prompt"],
            },
        },
    }


def run(args: dict) -> str:
    prompt  = args.get("prompt", "").strip()
    if not prompt:
        return "错误：prompt 参数不能为空"

    size    = args.get("size", "1024x1024").strip()
    quality = args.get("quality", "standard").strip()
    n        = min(int(args.get("n", 1)), 4)
    save_path = args.get("save_path", "").strip() or None

    try:
        client, cfg = _get_client()
        result = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size=size,
            quality=quality,
            n=n,
            response_format="url",
        )
    except Exception as e:
        msg = str(e)
        if "does not exist" in msg.lower() or "not supported" in msg.lower():
            return (
                f"❌ 当前 API 端点不支持 DALL-E 图片生成。\n"
                f"错误详情：{msg}\n"
                "建议：切换到 OpenAI 官方端点（https://api.openai.com/v1）\n"
                "或确认你的 API Key 已开通 DALL-E 权限。"
            )
        return f"❌ 图片生成失败：{msg}"

    lines = [f"✅ 已生成 {n} 张图片（{size}, {quality}）：\n"]
    for i, data in enumerate(result.data, 1):
        url = data.url
        lines.append(f"{i}. {url}")
        if save_path:
            ext      = Path(save_path).suffix or ".png"
            path_i   = str(Path(save_path).with_suffix("")) + (f"_{i}" if n > 1 else "") + ext
            saved    = _save_image(url, path_i)
            lines.append(f"   {saved.replace(saved.split('：')[0]+'：', '').split('\n')[0]}")
        else:
            lines.append(f"   {url}")
    return "\n".join(lines)
