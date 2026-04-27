"""
向量嵌入器：懒加载 sentence-transformers 模型，提供同步 encode() 接口。

模型：paraphrase-multilingual-MiniLM-L12-v2
  - 384 维，支持中英文，~120 MB（首次使用自动下载）
  - normalize_embeddings=True → 余弦相似度等价于点积

未安装 sentence-transformers 时 is_available() 返回 False，
encode() 抛出 ImportError，调用方负责捕获。
"""
from __future__ import annotations

_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
DIM = 384

_model = None


def is_available() -> bool:
    try:
        import sentence_transformers  # noqa: F401
        return True
    except ImportError:
        return False


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def encode(text: str) -> list[float]:
    """将文本编码为 384 维归一化向量（list[float]）。"""
    if not text or not text.strip():
        raise ValueError("不能对空文本编码")
    model = _get_model()
    vec = model.encode(text.strip(), normalize_embeddings=True)
    return list(vec)


def encode_batch(texts: list[str]) -> list[list[float]]:
    """批量编码，比逐条 encode() 快。"""
    if not texts:
        return []
    model = _get_model()
    vecs = model.encode(
        [t.strip() for t in texts],
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return [list(v) for v in vecs]
