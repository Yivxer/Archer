import sqlite3
import uuid
import json
from datetime import datetime, timedelta
from pathlib import Path
from core.paths import memory_db_path

DB_PATH = memory_db_path(Path(__file__).parent / "archer.db")

MEMORY_TYPES = [
    "identity",   # 身份信息（我是谁、价值观）
    "preference", # 偏好（做事方式、沟通风格）
    "project",    # 项目（进展、卡点）
    "decision",   # 决策（做了哪个选择、为什么）
    "todo",       # 待办
    "insight",    # 洞察（学到了什么）
    "risk",       # 风险（潜在问题）
    "context",    # 临时上下文
    "reflection", # 复盘摘要（/reflect 产出，不自动注入上下文）
    # A4：灵魂伴生体记忆类型
    "fact",
    "emotion_pattern",
    "value",
    "value_conflict",
    "life_theme",
    "self_narrative",
    "project_mythology",
    "relationship_pattern",
    "creative_identity",
    "growth_marker",
    "reflection_anchor",
]

BLOCK_TYPES = ("human", "persona", "preference", "decision", "event", "insight")

_TYPE_TO_BLOCK: dict[str, str] = {
    "fact": "human",
    "identity": "human",
    "self_narrative": "human",
    "preference": "preference",
    "creative_identity": "preference",
    "decision": "decision",
    "project": "decision",
    "todo": "decision",
    "reflection_anchor": "event",
    "growth_marker": "event",
    "context": "event",
}


def infer_block_type(memory_type: str, block_type: str | None = None) -> str:
    if block_type and block_type in BLOCK_TYPES:
        return block_type
    return _TYPE_TO_BLOCK.get(memory_type, "insight")


def normalize_label(label: str | None) -> str:
    return str(label or "").strip()[:80]
def init_db(db_path: str | Path | None = None):
    from memory.schema_setup import initialize_schema

    initialize_schema(db_path or DB_PATH)
def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _try_embed(memory_id: int, content: str) -> None:
    """静默计算并存储记忆向量嵌入（embedder 或 sqlite-vec 未安装时跳过）。"""
    try:
        from memory.embedder import encode
        from memory.vector_store import upsert
        upsert(memory_id, encode(content))
    except Exception:
        pass


def _clamp_depth(value: object) -> int:
    try:
        depth = int(str(value)) if not isinstance(value, (int, float)) else int(value)
    except Exception:
        depth = 3
    return max(1, min(5, depth))


def save(content: str, tags: str = "", type: str = "insight", importance: int = 3,
         source: str = "", scope: str = "user", confidence: float = 0.8,
         valid_until: str | None = None, session_id: str | None = None,
         depth: int = 3, block_type: str | None = None, label: str | None = None,
         *, db_path: str | Path | None = None) -> int:
    content = content.strip()
    tags = tags.strip()
    if type not in MEMORY_TYPES:
        type = "insight"
    try:
        importance = int(importance)
    except Exception:
        importance = 3
    importance = max(1, min(5, importance))
    depth = _clamp_depth(depth)
    resolved_block = infer_block_type(type, block_type)
    resolved_label = normalize_label(label)

    resolved_db_path = db_path or DB_PATH
    conn = sqlite3.connect(resolved_db_path)
    existing = conn.execute(
        "SELECT id FROM memories WHERE content = ? AND status = 'active' LIMIT 1",
        (content,),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE memories SET importance = MAX(importance, ?), depth = MAX(depth, ?), updated_at = ? WHERE id = ?",
            (importance, depth, _now(), existing[0]),
        )
        conn.commit()
        conn.close()
        return existing[0]

    cur = conn.execute(
        "INSERT INTO memories (content, tags, type, importance, depth, source, scope, confidence, "
        "valid_until, session_id, block_type, label, created_at, updated_at, observed_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (content, tags, type, importance, depth, source, scope, confidence,
         valid_until, session_id, resolved_block, resolved_label,
         _now(), _now(), json.dumps([_now()])),
    )
    conn.commit()
    mid = cur.lastrowid
    conn.close()
    assert mid is not None, "INSERT 未返回 lastrowid"
    if Path(resolved_db_path) == Path(DB_PATH):
        _try_embed(mid, content)
        # P2: 新记忆入库后自动矛盾检测
        contradiction_detect(mid, content)
    return mid

def _row_to_dict(r, has_date: bool = False, has_block: bool = False) -> dict:
    d = {
        "id": r[0], "content": r[1], "tags": r[2], "type": r[3],
        "importance": r[4],
        "depth": _clamp_depth(r[5] if len(r) > 5 else 3),
    }
    idx = 6
    if has_date:
        d["created_at"] = r[idx] if idx < len(r) else None
        idx += 1
    d["confidence"] = r[idx] if idx < len(r) else 0.8
    idx += 1
    d["valid_until"] = r[idx] if idx < len(r) else None
    idx += 1
    if has_block and idx < len(r):
        d["block_type"] = r[idx] if r[idx] else infer_block_type(d["type"])
        idx += 1
        d["label"] = r[idx] if idx < len(r) and r[idx] else ""
        idx += 1
    else:
        d["block_type"] = infer_block_type(d["type"])
        d["label"] = ""
    d["session_id"] = r[idx] if idx < len(r) and r[idx] else ""
    return d


_MEM_SELECT = (
    "id, content, tags, type, importance, depth, created_at, confidence, valid_until, block_type, label, session_id"
)
_MEM_SELECT_NO_DATE = (
    "id, content, tags, type, importance, depth, confidence, valid_until, block_type, label, session_id"
)

def list_by_type(memory_type: str, min_importance: int = 1, limit: int = 20) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        f"SELECT {_MEM_SELECT} FROM memories "
        "WHERE status = 'active' AND type = ? AND importance >= ? "
        "ORDER BY importance DESC, created_at DESC LIMIT ?",
        (memory_type, min_importance, limit),
    ).fetchall()
    conn.close()
    return [_row_to_dict(r, has_date=True, has_block=True) for r in rows]


def list_all(limit: int = 50) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        f"SELECT {_MEM_SELECT} FROM memories "
        "WHERE status = 'active' ORDER BY importance DESC, updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [_row_to_dict(r, has_date=True, has_block=True) for r in rows]

def get_by_ids(ids: list[int]) -> dict[int, dict]:
    """批量按 ID 获取活跃记忆，返回 {id: memory_dict}。"""
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            f"SELECT {_MEM_SELECT} "
            f"FROM memories WHERE id IN ({placeholders}) AND status = 'active'",
            ids,
        ).fetchall()
        result = {r[0]: _row_to_dict(r, has_date=True, has_block=True) for r in rows}
    except sqlite3.OperationalError:
        rows = conn.execute(
            f"SELECT id, content, tags, type, importance, created_at, confidence, valid_until "
            f"FROM memories WHERE id IN ({placeholders}) AND status = 'active'",
            ids,
        ).fetchall()
        result = {
            r[0]: {
                "id": r[0], "content": r[1], "tags": r[2], "type": r[3],
                "importance": r[4], "depth": 3, "created_at": r[5],
                "confidence": r[6], "valid_until": r[7],
            }
            for r in rows
        }
    conn.close()
    return result


def _fts_phrase(keyword: str) -> str:
    """Bind user text as one FTS5 phrase.

    Parentheses, quotes, and words like AND/OR are literal in retrieval
    questions. Passing them through unquoted makes MATCH raise, and the
    previous fallback scanned every memory with LIKE.
    """
    return '"' + keyword.replace('"', '""') + '"'


def search(keyword: str, limit: int = 10, block_type: str | None = None,
           label: str | None = None) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    filter_args: list = []
    where_extra = ""
    if block_type and block_type in BLOCK_TYPES:
        where_extra += " AND m.block_type = ?"
        filter_args.append(block_type)
    if label:
        where_extra += " AND m.label = ?"
        filter_args.append(normalize_label(label))
    # FTS5 trigram 索引需要 ≥3 个字符，短词直接走 LIKE
    use_fts = len(keyword.strip()) >= 3
    try:
        if not use_fts:
            raise ValueError("keyword too short for FTS5 trigram")
        rows = conn.execute(
            f"SELECT m.id, m.content, m.tags, m.type, m.importance, m.depth, m.created_at, "
            f"m.confidence, m.valid_until, m.block_type, m.label "
            f"FROM memories_fts f JOIN memories m ON f.rowid = m.id "
            f"WHERE memories_fts MATCH ? AND m.status = 'active'{where_extra} "
            f"ORDER BY m.importance DESC, rank LIMIT ?",
            (_fts_phrase(keyword), *filter_args, limit),
        ).fetchall()
    except Exception:
        like = f"%{keyword}%"
        like_filters = ["status = 'active'", "(content LIKE ? OR tags LIKE ?)"]
        like_args: list = [like, like]
        if block_type and block_type in BLOCK_TYPES:
            like_filters.append("block_type = ?")
            like_args.append(block_type)
        if label:
            like_filters.append("label = ?")
            like_args.append(normalize_label(label))
        rows = conn.execute(
            f"SELECT {_MEM_SELECT} FROM memories "
            f"WHERE {' AND '.join(like_filters)} "
            f"ORDER BY importance DESC LIMIT ?",
            (*like_args, limit),
        ).fetchall()
    conn.close()
    return [_row_to_dict(r, has_date=True, has_block=True) for r in rows]

def delete(mid: int):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM memories WHERE id = ?", (mid,))
    conn.commit()
    conn.close()
    try:
        from memory.vector_store import delete as vec_delete
        vec_delete(mid)
    except Exception:
        pass

def update(mid: int, content: str, tags: str | None = None,
           type: str | None = None, importance: int | None = None,
           depth: int | None = None) -> bool:
    fields = ["content = ?", "updated_at = ?"]
    values: list = [content.strip(), _now()]

    if tags is not None:
        fields.append("tags = ?")
        values.append(tags.strip())
    if type is not None:
        fields.append("type = ?")
        values.append(type if type in MEMORY_TYPES else "insight")
    if importance is not None:
        fields.append("importance = ?")
        values.append(max(1, min(5, int(importance))))
    if depth is not None:
        fields.append("depth = ?")
        values.append(_clamp_depth(depth))

    values.append(mid)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        f"UPDATE memories SET {', '.join(fields)} WHERE id = ? AND status = 'active'",
        values,
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok

def archive(mid: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "UPDATE memories SET status = 'archived', archived_at = ?, updated_at = ? "
        "WHERE id = ? AND status = 'active'",
        (_now(), _now(), mid),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok

def recent(limit: int = 5) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        f"SELECT {_MEM_SELECT_NO_DATE} FROM memories "
        "WHERE status = 'active' ORDER BY importance DESC, updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [_row_to_dict(r, has_block=True) for r in rows]

def high_importance(min_importance: int = 4, limit: int = 3) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        f"SELECT {_MEM_SELECT_NO_DATE} FROM memories "
        "WHERE status = 'active' AND importance >= ? "
        "AND type IN ('identity', 'preference', 'project', 'decision', 'value', 'self_narrative', 'insight', 'fact', 'growth_marker') "
        "ORDER BY importance DESC, updated_at DESC LIMIT ?",
        (min_importance, limit),
    ).fetchall()
    conn.close()
    return [_row_to_dict(r, has_block=True) for r in rows]


def list_by_block_type(block_type: str, limit: int = 20, label: str | None = None) -> list[dict]:
    if block_type not in BLOCK_TYPES:
        return []
    conn = sqlite3.connect(DB_PATH)
    if label:
        rows = conn.execute(
            f"SELECT {_MEM_SELECT} FROM memories "
            "WHERE status = 'active' AND block_type = ? AND label = ? "
            "ORDER BY importance DESC, updated_at DESC LIMIT ?",
            (block_type, normalize_label(label), limit),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {_MEM_SELECT} FROM memories "
            "WHERE status = 'active' AND block_type = ? "
            "ORDER BY importance DESC, updated_at DESC LIMIT ?",
            (block_type, limit),
        ).fetchall()
    conn.close()
    return [_row_to_dict(r, has_date=True, has_block=True) for r in rows]


def list_compaction_candidates(limit: int = 50) -> list[dict]:
    """Return active memories most eligible for compaction (low importance, least recently used)."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        f"SELECT {_MEM_SELECT} FROM memories "
        "WHERE status = 'active' "
        "ORDER BY importance ASC, COALESCE(last_used_at, created_at) ASC, id ASC "
        "LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [_row_to_dict(r, has_date=True, has_block=True) for r in rows]


def update_last_used(mid: int):
    """更新记忆的最后使用时间，用于 retrieve 调用后追踪活跃度。同时追加 observed_at。"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE memories SET last_used_at = ? WHERE id = ?", (_now(), mid))
    conn.commit()
    conn.close()
    observed(mid)


# ── Pending Memories（持久化候选记忆）─────────────────────────────────────────

# ── P1: 待确认记忆审阅（已抽到 memory/store_pending.py） ──────────────────────
# add_pending / list_pending / count_pending / update_pending / accept_pending / reject_pending
# 全部迁移到 store_pending.py，下方 re-export 保持向后兼容


def count_active() -> int:
    conn = sqlite3.connect(DB_PATH)
    n = conn.execute("SELECT COUNT(*) FROM memories WHERE status = 'active'").fetchone()[0]
    conn.close()
    return n


# ── Themes / Projects / Soul Proposals（已抽到独立模块） ────────────────────────
# store_themes.py:         save_theme / list_themes / link_memory_to_theme / get_theme_memories / get_memories_for_detection
# store_projects.py:       create_project / list_projects / get_project / get_project_by_name / archive_project / log_project_event / get_project_events
# store_soul_proposals.py: add_soul_proposal / list_soul_proposals / count_soul_proposals / resolve_soul_proposal
# 下方 re-export 保持向后兼容



# ── Session ID 生成 ──────────────────────────────────────────────────────────────

def generate_session_id() -> str:
    """生成会话 ID：日期时间 + 短 UUID。"""
    short_uuid = str(uuid.uuid4())[:8]
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + short_uuid


# ── Importance Decay（v1.2 Phase 3）────────────────────────────────────────────

# 只对短中期记忆类型执行衰减，不影响身份/决策/偏好
_DECAY_TYPES = {"context", "state", "todo", "risk", "project"}
_NO_DECAY_TYPES = {"identity", "decision", "preference"}


def run_importance_decay() -> int:
    """
    对超期未使用的短中期记忆执行 importance -1 衰减。
    - context/state：超 30 天未使用 → importance -1
    - todo/risk/project：超 60 天未使用 → importance -1
    - 最低降到 1，不自动 archive，不自动删除。
    返回影响的记忆条数。
    """
    now = datetime.now()
    cutoff_30 = (now - timedelta(days=30)).isoformat(timespec="seconds")
    cutoff_60 = (now - timedelta(days=60)).isoformat(timespec="seconds")

    conn = sqlite3.connect(DB_PATH)
    affected = 0

    # context/state 30天
    for t in ("context", "state"):
        cur = conn.execute(
            """UPDATE memories SET importance = MAX(1, importance - 1), updated_at = ?
               WHERE type = ? AND status = 'active' AND importance > 1
               AND (last_used_at IS NULL OR last_used_at < ?)""",
            (_now(), t, cutoff_30),
        )
        affected += cur.rowcount

    # todo/risk/project 60天
    for t in ("todo", "risk", "project"):
        cur = conn.execute(
            """UPDATE memories SET importance = MAX(1, importance - 1), updated_at = ?
               WHERE type = ? AND status = 'active' AND importance > 1
               AND (last_used_at IS NULL OR last_used_at < ?)""",
            (_now(), t, cutoff_60),
        )
        affected += cur.rowcount

    conn.commit()
    conn.close()
    return affected


# ── P1: 记忆时间线 ────────────────────────────────────────────────────────────

import textwrap

_GRACE_DAYS = 90  # >90 天未确认 → stale


def observed(mid: int) -> None:
    """记录该记忆被确认/引用，追加当前时间戳到 observed_at。"""
    now = _now()
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT observed_at FROM memories WHERE id = ?", (mid,)).fetchone()
    if not row:
        conn.close()
        return
    try:
        history = json.loads(row[0]) if row[0] else []
    except Exception:
        history = []
    history.append(now)
    conn.execute(
        "UPDATE memories SET observed_at = ?, updated_at = ?, last_used_at = ? WHERE id = ?",
        (json.dumps(history, ensure_ascii=False), now, now, mid),
    )
    conn.commit()
    conn.close()


def freshness_check() -> list[dict]:
    """
    扫描所有 active 记忆，将 > _GRACE_DAYS 天未被确认的记忆标记为 stale。
    返回被标记的记忆列表（含 oldest_observed_at）。
    """
    cutoff = (datetime.now() - timedelta(days=_GRACE_DAYS)).isoformat(timespec="seconds")
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, content, observed_at, type FROM memories WHERE status = 'active'",
    ).fetchall()
    stale = []
    for r in rows:
        mid, content, obs_raw, mtype = r
        if mtype in ("identity", "preference", "decision"):
            continue  # 核心记忆不过期
        try:
            history = json.loads(obs_raw) if obs_raw and obs_raw != "[]" else []
        except Exception:
            history = []
        oldest = history[0] if history else None
        last = history[-1] if history else None
        if last is None or last < cutoff:
            conn.execute("UPDATE memories SET status = 'stale' WHERE id = ?", (mid,))
            stale.append({
                "id": mid, "content": content[:80], "type": mtype,
                "observations": len(history),
                "last_observed": last or "从未",
            })
    conn.commit()
    conn.close()
    return stale


def list_stale() -> list[dict]:
    """列出所有过期记忆。"""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, content, type, importance, observed_at FROM memories WHERE status = 'stale'",
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "content": r[1], "type": r[2], "importance": r[3],
         "observed_at": r[4]}
        for r in rows
    ]


def refresh_memory(mid: int) -> bool:
    """手动刷新过期记忆为 active。"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "UPDATE memories SET status = 'active', updated_at = ? WHERE id = ? AND status = 'stale'",
        (_now(), mid),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


# ── P2: 矛盾检测（已抽到 memory/store_quality.py） ───────────────────────────
# 相似度工具 / 重复检测 / 低质量过滤 / 矛盾检测全部迁移到 store_quality.py
# 下方 re-export 保持向后兼容




# ── P3: 记忆分类体系 ───────────────────────────────────────────────────────────

# 25 种 memory type → 5 大归组
MEMORY_GROUPS: dict[str, dict] = {
    "who_am_i": {
        "label": "我是谁",
        "icon": "heart",
        "types": ["identity", "value", "value_conflict", "self_narrative", "reflection_anchor"],
        "question": "我坚持什么？我在纠结什么？",
    },
    "how_i_work": {
        "label": "我怎么做事",
        "icon": "settings",
        "types": ["preference", "fact", "decision", "reflection"],
        "question": "什么方式让我效率最高？",
    },
    "emotion_world": {
        "label": "我的情绪模式",
        "icon": "waves",
        "types": ["emotion_pattern", "relationship_pattern", "context"],
        "question": "什么情境会触发我？",
    },
    "what_i_do": {
        "label": "我在做什么",
        "icon": "compass",
        "types": ["project", "project_mythology", "todo", "risk"],
        "question": "项目到哪了？为什么重要？",
    },
    "how_i_grow": {
        "label": "我在变",
        "icon": "trending_up",
        "types": ["growth_marker", "creative_identity", "insight", "life_theme"],
        "question": "相比之前，我变了什么？",
    },
}


def memory_group_for_type(mtype: str) -> str:
    """返回给定 type 所属的 group key。"""
    for key, group in MEMORY_GROUPS.items():
        if mtype in group["types"]:
            return key
    return "who_am_i"  # fallback


def count_by_groups() -> dict:
    """返回每个 group 的 active 记忆数量。"""
    conn = sqlite3.connect(DB_PATH)
    result = {}
    for key, group in MEMORY_GROUPS.items():
        placeholders = ",".join("?" * len(group["types"]))
        count = conn.execute(
            f"SELECT COUNT(*) FROM memories WHERE status = 'active' AND type IN ({placeholders})",
            group["types"],
        ).fetchone()[0]
        result[key] = count
    conn.close()
    return result


def memories_by_group(group_key: str, limit: int = 30) -> list[dict]:
    """返回指定 group 下的记忆列表。"""
    if group_key not in MEMORY_GROUPS:
        return []
    types = MEMORY_GROUPS[group_key]["types"]
    placeholders = ",".join("?" * len(types))
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        f"SELECT id, content, type, importance, depth, created_at, confidence, block_type, label "
        f"FROM memories WHERE status = 'active' AND type IN ({placeholders}) "
        f"ORDER BY importance DESC, updated_at DESC LIMIT ?",
        [*types, limit],
    ).fetchall()
    conn.close()
    return [
        {
            "id": r[0], "content": r[1], "type": r[2],
            "importance": r[3], "depth": r[4], "created_at": r[5], "confidence": r[6],
            "block_type": r[7] if len(r) > 7 and r[7] else infer_block_type(r[2]),
            "label": r[8] if len(r) > 8 and r[8] else "",
        }
        for r in rows
    ]


# ── P4: 记忆更新 ──────────────────────────────────────────────────────────────

def update_memory_content(mid: int, content: str) -> bool:
    """更新已有记忆的内容，保留原 type/importance/depth。返回是否成功。"""
    content = content.strip()
    if not content or len(content) < 10:
        return False
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "UPDATE memories SET content = ?, updated_at = ? WHERE id = ? AND status = 'active'",
        (content, _now(), mid),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    if ok:
        _try_embed(mid, content)
        observed(mid)
    return ok


def evolve_memory(mid: int, content: str, mtype: str | None = None,
                  importance: int | None = None, depth: int | None = None) -> bool:
    """演进记忆：更新内容，可选更新 type/importance/depth。
    旧内容存为标签中的历史。"""
    content = content.strip()
    if not content or len(content) < 10:
        return False
    conn = sqlite3.connect(DB_PATH)
    old = conn.execute(
        "SELECT content, type, importance, depth FROM memories WHERE id = ? AND status = 'active'",
        (mid,),
    ).fetchone()
    if not old:
        conn.close()
        return False
    old_content = old[0]
    new_type = mtype if mtype and mtype in MEMORY_TYPES else old[1]
    new_imp = max(1, min(5, int(importance))) if importance is not None else old[2]
    new_depth = _clamp_depth(depth) if depth is not None else old[3]
    # 把旧内容追加到 observed_at
    observed_at = _now()
    conn.execute(
        "UPDATE memories SET content = ?, type = ?, importance = ?, depth = ?, "
        "updated_at = ?, observed_at = ? WHERE id = ? AND status = 'active'",
        (content, new_type, new_imp, new_depth, _now(), observed_at, mid),
    )
    # 给旧记忆内容加个追溯标签
    if old_content != content:
        conn.execute(
            "UPDATE memories SET tags = CASE WHEN tags = '' THEN ? ELSE tags || ',' || ? END WHERE id = ?",
            (f"曾:{old_content[:40]}", f"曾:{old_content[:40]}", mid),
        )
    conn.commit()
    conn.close()
    _try_embed(mid, content)
    return True


def count_contradictions() -> int:
    conn = sqlite3.connect(DB_PATH)
    n = conn.execute("SELECT COUNT(*) FROM contradictions WHERE status = 'open'").fetchone()[0]
    conn.close()
    return n


def count_stale() -> int:
    conn = sqlite3.connect(DB_PATH)
    n = conn.execute("SELECT COUNT(*) FROM memories WHERE status = 'stale'").fetchone()[0]
    conn.close()
    return n


def recent_memories_since(since_days: int = 7) -> list[dict]:
    """返回最近 N 天内创建的活跃记忆。"""
    cutoff = (datetime.now() - timedelta(days=since_days)).isoformat(timespec="seconds")
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, content, type, importance, depth, created_at, confidence FROM memories "
        "WHERE status = 'active' AND created_at >= ? ORDER BY created_at DESC LIMIT 50",
        (cutoff,),
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "content": r[1], "type": r[2],
         "importance": r[3], "depth": r[4], "created_at": r[5], "confidence": r[6]}
        for r in rows
    ]


# ---------------------------------------------------------------------------
# 兼容性 re-export：质量检查与矛盾检测（已迁移到 store_quality.py）
# ---------------------------------------------------------------------------
# 历史代码通过 `from memory.store import contradiction_detect` 等方式访问，
# 这里 re-export 保持向后兼容。新代码请直接 from memory.store_quality import X。

from memory.store_quality import (  # noqa: F401  (re-export)
    _EN_STOP,
    _TOPIC_STOPCHARS,
    _is_contradiction,
    _keyword_overlap,
    _ngram_similarity,
    _text_similarity,
    _topic_keywords,
    contradiction_detect,
    is_duplicate_pending,
    is_low_quality_memory,
    list_contradictions,
    resolve_contradiction,
)

from memory.store_pending import (  # noqa: F401  (re-export)
    accept_pending,
    add_pending,
    count_pending,
    list_pending,
    reject_pending,
    update_pending,
)

from memory.store_themes import (  # noqa: F401  (re-export)
    get_memories_for_detection,
    get_theme_memories,
    link_memory_to_theme,
    list_themes,
    save_theme,
)

from memory.store_projects import (  # noqa: F401  (re-export)
    archive_project,
    create_project,
    get_project,
    get_project_by_name,
    get_project_events,
    list_projects,
    log_project_event,
)

from memory.store_soul_proposals import (  # noqa: F401  (re-export)
    add_soul_proposal,
    count_soul_proposals,
    list_soul_proposals,
    resolve_soul_proposal,
)

