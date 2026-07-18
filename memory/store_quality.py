"""记忆质量检查与矛盾检测（从 memory/store.py 抽出）。

包含：
- 文本相似度工具（_ngram_similarity / _text_similarity / _topic_keywords / _keyword_overlap）
- 重复检测（is_duplicate_pending）
- 低质量过滤（is_low_quality_memory）
- 矛盾检测（_is_contradiction / contradiction_detect / list_contradictions / resolve_contradiction）

依赖：DB_PATH 通过 `import memory.store as _store` 动态查找，
确保测试修改 _store.DB_PATH 生效。
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

import memory.store as _store


def _now() -> str:
    """当前 ISO 时间字符串（秒精度）。与 store._now 实现一致。"""
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 文本相似度工具
# ---------------------------------------------------------------------------

def _ngram_similarity(a: str, b: str, n: int = 2) -> float:
    """基于字符 n-gram 的 Jaccard 相似度。用于记忆去重。"""
    if len(a) < n or len(b) < n:
        return 0.0
    ng_a = Counter(a[i:i+n] for i in range(len(a) - n + 1))
    ng_b = Counter(b[i:i+n] for i in range(len(b) - n + 1))
    intersection = sum((ng_a & ng_b).values())
    union = sum((ng_a | ng_b).values())
    return intersection / union if union > 0 else 0.0


def _text_similarity(a: str, b: str) -> float:
    """综合字符级和 bigram 的文本相似度。对中文和英文都适用。"""
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.85
    # 字符级 Jaccard（单字集合交集）
    chars_a = set(a)
    chars_b = set(b)
    char_sim = len(chars_a & chars_b) / max(len(chars_a | chars_b), 1)
    # Bigram Jaccard
    bg_sim = _ngram_similarity(a, b, n=2)
    return char_sim * 0.3 + bg_sim * 0.7


# 中文停用字（在关键词提取时跳过）
_TOPIC_STOPCHARS: set[str] = {
    "用", "户", "希", "望", "要", "求", "认", "为", "觉", "得",
    "这", "个", "那", "个", "自", "己", "什", "么", "可", "以",
    "能", "够", "应", "该", "需", "已", "经", "还", "不", "但",
    "一", "些", "样", "些", "那", "比", "较", "非", "常", "很",
    "都", "也", "就", "再", "把", "被", "让", "给", "从", "在",
    "与", "和", "的", "了", "会", "对", "等", "或", "而", "及",
    "并", "中", "上", "下", "前", "后", "来", "去", "它", "他",
    "她", "其", "你", "我", "且", "虽", "更", "最", "所", "着",
    "却", "又", "走", "向", "做", "成", "为", "使", "进", "到",
    "化", "取", "期", "望", "念", "想", "法", "表", "方", "式",
}

# 英文停用词（_topic_keywords 内部使用）
_EN_STOP = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "under", "again",
    "further", "then", "once", "here", "there", "when", "where", "why",
    "how", "all", "both", "each", "few", "more", "most", "other", "some",
    "such", "no", "nor", "not", "only", "own", "same", "so", "than",
    "too", "very", "just", "about", "now", "it", "its", "this", "that",
    "these", "those", "and", "but", "or", "if", "while", "because",
    "until", "up", "out", "off", "over", "my", "your", "his", "her", "our", "their",
}


def _topic_keywords(text: str) -> set[str]:
    """从中文文本中提取实质性话题关键词（2-3 字 ngram，跳过停用字）。
    同时保留英文单词 2-3 词短语，避免"Archer 是我的 AI"被提取为空。"""
    ngrams: set[str] = set()
    # 中文 ngram
    cleaned_cn = "".join(c for c in text if "\u4e00" <= c <= "\u9fff" and c not in _TOPIC_STOPCHARS)
    for n in (2, 3):
        for i in range(len(cleaned_cn) - n + 1):
            ngrams.add(cleaned_cn[i:i + n])
    # 英文 ngram（单词级别）
    en_words = [w.lower() for w in re.findall(r'[a-zA-Z]{2,}', text) if w.lower() not in _EN_STOP]
    for n in (2, 3):
        for i in range(len(en_words) - n + 1):
            ngrams.add(" ".join(en_words[i:i + n]))
    return ngrams


def _keyword_overlap(a: str, b: str, min_shared: int = 3) -> bool:
    """两个文本是否共享足够多的实质性关键词 ngram。
    用于补充字符相似度对中文近义表述的漏检。"""
    kw_a = _topic_keywords(a)
    kw_b = _topic_keywords(b)
    shared = kw_a & kw_b
    return len(shared) >= min_shared


# ---------------------------------------------------------------------------
# 重复与低质量过滤
# ---------------------------------------------------------------------------

def is_duplicate_pending(
    content: str, threshold: float = 0.25, *, db_path: str | Path | None = None,
) -> bool:
    """检查 content 是否与已有的 pending_memories 或 active memories 高度相似。
    返回 True 表示存在重复，不应再添加。"""
    content = content.strip()
    if len(content) < 10:
        return False  # 太短的不做模糊匹配
    conn = sqlite3.connect(db_path or _store.DB_PATH)
    try:
        # 检查 pending_memories
        pending_rows = conn.execute(
            "SELECT content FROM pending_memories"
        ).fetchall()
        for r in pending_rows:
            if _text_similarity(content, r[0]) >= threshold:
                conn.close()
                return True
            if _keyword_overlap(content, r[0], min_shared=3):
                conn.close()
                return True
        # 检查 active memories（更严格阈值，避免误判）
        active_rows = conn.execute(
            "SELECT content FROM memories WHERE status = 'active' ORDER BY updated_at DESC LIMIT 150"
        ).fetchall()
        active_threshold = max(threshold, 0.40)
        for r in active_rows:
            if _text_similarity(content, r[0]) >= active_threshold:
                conn.close()
                return True
            if _keyword_overlap(content, r[0], min_shared=4):
                conn.close()
                return True
        conn.close()
        return False
    except Exception:
        conn.close()
        return False


def is_low_quality_memory(content: str, mtype: str = "insight") -> bool:
    """过滤低质量记忆。返回 True 表示应该丢弃。"""
    content = content.strip()
    # 太短
    if len(content) < 10:
        return True
    # 太长：超过 200 字可能是啰嗦话
    if len(content) > 200:
        return True
    # 纯事实性低价值短语（太泛了）
    low_value_patterns = [
        "好的", "明白了", "知道了", "嗯", "对", "是的",
        "可以的", "没问题", "就这样", "行", "好",
        "他说", "我说", "用户说", "你说",
    ]
    if any(content == p or content.startswith(p) and len(content) < 12 for p in low_value_patterns):
        return True
    # 无实质内容：只有代词和连接词
    filler_ratio = sum(1 for c in content if c in "的了我是在有这和那就也他她对它") / max(len(content), 1)
    if filler_ratio > 0.55 and len(content) < 30:
        return True
    # 重复相同字符（如 "好好好好好"）
    if len(content) > 4 and len(set(content)) == 1:
        return True
    return False


# ---------------------------------------------------------------------------
# 矛盾检测
# ---------------------------------------------------------------------------

def _is_contradiction(a: str, b: str) -> bool:
    """
    判断两条记忆是否语义矛盾。
    纯规则：不依赖模型——基于否定词 + 相似度。
    高相似度 + 否定词 = 矛盾。
    """
    NEGATORS = ["不", "不再", "从不", "没", "没有", "否定", "取消", "放弃",
                "don't", "not", "never", "no longer", "stop", "quit"]
    a_neg = any(w in a for w in NEGATORS)
    b_neg = any(w in b for w in NEGATORS)
    # 一个肯定一个否定 + 文本相似 → 矛盾
    if a_neg == b_neg:
        return False
    sim = SequenceMatcher(None, a, b).ratio()
    return sim > 0.55


def contradiction_detect(new_mid: int, new_content: str) -> list[int]:
    """
    新记忆入库后调用。与所有 active 记忆比对，发现矛盾则记录到 contradictions 表。
    返回矛盾记忆 ID 列表。
    """
    conn = sqlite3.connect(_store.DB_PATH)
    rows = conn.execute(
        "SELECT id, content FROM memories WHERE status = 'active' AND id != ?", (new_mid,),
    ).fetchall()
    conflicts = []
    for r in rows:
        if _is_contradiction(new_content, r[1]):
            try:
                a, b = sorted([new_mid, r[0]])
                conn.execute(
                    "INSERT INTO contradictions (memory_a, memory_b, description, status, created_at) "
                    "VALUES (?, ?, ?, 'open', ?)",
                    (a, b, f"{a} ↔ {b}", _now()),
                )
                conflicts.append(r[0])
            except Exception:
                pass  # UNIQUE 冲突：已存在，跳过
    conn.commit()
    conn.close()
    return conflicts


def list_contradictions() -> list[dict]:
    """列出所有未解决的矛盾。"""
    conn = sqlite3.connect(_store.DB_PATH)
    rows = conn.execute(
        "SELECT c.id, c.memory_a, c.memory_b, c.description, c.status, c.created_at, "
        "ma.content, mb.content "
        "FROM contradictions c "
        "JOIN memories ma ON ma.id = c.memory_a "
        "JOIN memories mb ON mb.id = c.memory_b "
        "WHERE c.status = 'open' ORDER BY c.created_at DESC",
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "memory_a": r[1], "memory_b": r[2], "description": r[3],
         "status": r[4], "created_at": r[5],
         "content_a": r[6][:80], "content_b": r[7][:80]}
        for r in rows
    ]


def resolve_contradiction(cid: int, keep_memory: int) -> bool:
    """
    裁决矛盾：保留 keep_memory，归档另一边。
    """
    conn = sqlite3.connect(_store.DB_PATH)
    row = conn.execute(
        "SELECT memory_a, memory_b FROM contradictions WHERE id = ?", (cid,),
    ).fetchone()
    if not row:
        conn.close()
        return False
    discard = row[0] if row[1] == keep_memory else row[1]
    conn.execute("UPDATE contradictions SET status = 'resolved', resolved_at = ? WHERE id = ?",
                 (_now(), cid))
    conn.execute("UPDATE memories SET status = 'archived', archived_at = ? WHERE id = ?",
                 (_now(), discard))
    conn.commit()
    conn.close()
    return True
