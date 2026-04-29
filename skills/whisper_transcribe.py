import subprocess
import tempfile
import re
from pathlib import Path

SKILL = {
    "name": "whisper_transcribe",
    "description": "将音频或视频文件转录为文字（支持中文），用于整理剪辑素材、会议记录、播客笔记",
    "version": "1.0.0",
    "author": "archer-builtin",
}

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
MODELS = {"tiny", "base", "small", "medium"}
MAX_MEDIA_BYTES = 2 * 1024 * 1024 * 1024

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "whisper_transcribe",
            "description": (
                "将本地音频或视频文件转录为文字。"
                "支持中文、英文等多语言，自动识别语言。"
                "视频文件会先提取音轨再转录。"
                "model=tiny/base/small/medium，默认 base（速度与精度平衡）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "音频或视频文件的绝对路径或 ~/... 路径",
                    },
                    "model": {
                        "type": "string",
                        "enum": ["tiny", "base", "small", "medium"],
                        "description": "Whisper 模型大小：tiny 最快、medium 最准，默认 base",
                    },
                    "language": {
                        "type": "string",
                        "description": "语言代码，如 zh（中文）、en（英文），不填则自动检测",
                    },
                },
                "required": ["path"],
            },
        },
    }

def _extract_audio(video_path: Path, out_path: Path) -> bool:
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(video_path), "-vn", "-ar", "16000",
         "-ac", "1", "-c:a", "pcm_s16le", str(out_path)],
        capture_output=True, timeout=300
    )
    return result.returncode == 0

def run(args: dict) -> str:
    raw_path = args.get("path", "").strip()
    if not raw_path:
        return "错误：path 不能为空"

    p = Path(raw_path).expanduser().resolve()
    if not p.exists():
        return f"文件不存在：{p}"
    if not p.is_file():
        return f"不是文件：{p}"
    try:
        size = p.stat().st_size
    except OSError as e:
        return f"无法读取文件信息：{e}"
    if size > MAX_MEDIA_BYTES:
        return f"文件过大：{size // (1024 * 1024)} MB，上限 {MAX_MEDIA_BYTES // (1024 * 1024)} MB"

    ext = p.suffix.lower()
    model = args.get("model", "base")
    lang  = args.get("language", "")
    if model not in MODELS:
        return f"不支持的模型：{model}。可选：{', '.join(sorted(MODELS))}"
    if lang and not re.fullmatch(r"[A-Za-z]{2,8}(-[A-Za-z0-9]{2,8})?", lang):
        return "错误：language 必须是类似 zh、en、zh-CN 的语言代码"

    is_video = ext in VIDEO_EXTS
    is_audio = ext in AUDIO_EXTS

    if not is_video and not is_audio:
        supported = ", ".join(sorted(AUDIO_EXTS | VIDEO_EXTS))
        return f"不支持的格式：{ext}。支持：{supported}"

    try:
        import whisper
    except ImportError:
        return "错误：未安装 openai-whisper，请运行：pip install openai-whisper"

    audio_path = p
    tmp_file   = None

    try:
        if is_video:
            tmp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp_file.close()
            tmp_path = Path(tmp_file.name)
            if not _extract_audio(p, tmp_path):
                return f"视频音轨提取失败，请确认 ffmpeg 可用"
            audio_path = tmp_path

        wmodel = whisper.load_model(model)
        opts   = {"fp16": False}
        if lang:
            opts["language"] = lang

        result = wmodel.transcribe(str(audio_path), **opts)
        text   = result.get("text", "").strip()
        detected_lang = result.get("language", "")

        header = f"🎙 {p.name}  模型={model}  语言={detected_lang or '自动'}\n\n"
        return header + (text if text else "（未识别到文字）")

    except Exception as e:
        return f"转录失败：{e}"
    finally:
        if tmp_file:
            Path(tmp_file.name).unlink(missing_ok=True)
