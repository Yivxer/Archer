"""
Phase 2: 自我批评机制

self_critiques 表管理，提供 scan / list / view / dismiss / create 接口。

设计原则：
- critique 只是观察，不自动 apply 到任何文件或配置
- weekly scan 默认关闭
- 用户负反馈触发有限流保护
- evidence_json 必填，强制有证据
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _conn() -> sqlite3.Connection:
    import memory.store as _store
    conn = sqlite3.connect(_store.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── 表初始化（由 store.init_db 调用）────────────────────────────────────────────

def init_critiques_table() -> None:
    conn = _conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS self_critiques (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at         TEXT    NOT NULL,
            session_id         TEXT,
            source             TEXT    NOT NULL,
            title              TEXT    NOT NULL,
            observation        TEXT    NOT NULL,
            hypothesis         TEXT,
            evidence_json      TEXT    NOT NULL DEFAULT '[]',
            severity           INTEGER DEFAULT 3,
            confidence         REAL    DEFAULT 0.7,
            suggested_direction TEXT,
            scope              TEXT    DEFAULT 'observation_only',
            status             TEXT    DEFAULT 'open',
            user_notes         TEXT,
            dismissed_reason   TEXT,
            CHECK (length(observation) >= 30)
        )
    """)
    # 幂等：为已有数据库补列
    for ddl in [
        "ALTER TABLE self_critiques ADD COLUMN session_id TEXT",
        "ALTER TABLE self_critiques ADD COLUMN hypothesis TEXT",
        "ALTER TABLE self_critiques ADD COLUMN suggested_direction TEXT",
        "ALTER TABLE self_critiques ADD COLUMN dismissed_reason TEXT",
    ]:
        try:
            conn.execute(ddl)
        except Exception:
            pass
    conn.commit()
    conn.close()


# ── CRUD ────────────────────────────────────────────────────────────────────────

def create_critique(
    title: str,
    observation: str,
    source: str = "manual",
    evidence: list[str] | None = None,
    session_id: str | None = None,
    hypothesis: str = "",
    suggested_direction: str = "",
    severity: int = 3,
    confidence: float = 0.7,
    scope: str = "observation_only",
) -> int:
    """创建一条自我批评记录，返回 ID。"""
    if len(observation) < 30:
        raise ValueError("observation 至少需要 30 字")
    evidence_json = json.dumps(evidence or [], ensure_ascii=False)
    conn = _conn()
    cur = conn.execute(
        """INSERT INTO self_critiques
           (created_at, session_id, source, title, observation, hypothesis,
            evidence_json, severity, confidence, suggested_direction, scope, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')""",
        (_now(), session_id, source, title, observation, hypothesis,
         evidence_json, severity, confidence, suggested_direction, scope),
    )
    cid = cur.lastrowid
    conn.commit()
    conn.close()
    return cid


def list_critiques(status: str = "open") -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM self_critiques WHERE status = ? ORDER BY created_at DESC",
        (status,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_critique(cid: int) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM self_critiques WHERE id = ?", (cid,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def dismiss_critique(cid: int, reason: str = "") -> bool:
    conn = _conn()
    conn.execute(
        "UPDATE self_critiques SET status='dismissed', dismissed_reason=? WHERE id=?",
        (reason, cid),
    )
    conn.commit()
    conn.close()
    return True


# ── 扫描生成批评 ────────────────────────────────────────────────────────────────

def scan_critiques(cfg: dict) -> list[dict]:
    """
    扫描当前状态，生成自我批评候选。
    v1.2.0：只扫描可观察的结构性问题，不接入 LLM。
    """
    results = []

    # 检查 pending_memories 积压
    try:
        conn = _conn()
        pending_count = conn.execute(
            "SELECT COUNT(*) FROM pending_memories"
        ).fetchone()[0]
        conn.close()
        if pending_count >= 15:
            obs = (
                f"pending_memories 积压 {pending_count} 条，长期未审阅。"
                f"可能导致有价值的观察丢失，或因积压过多降低记忆质量。"
            )
            existing = list_critiques("open")
            if not any("pending_memories" in c.get("title", "") for c in existing):
                cid = create_critique(
                    title=f"待确认记忆积压（{pending_count}条）",
                    observation=obs,
                    source="scan",
                    evidence=[f"pending_memories 表当前有 {pending_count} 条未审阅记录"],
                    severity=2,
                    confidence=0.9,
                    scope="observation_only",
                )
                results.append({"id": cid, "title": f"待确认记忆积压（{pending_count}条）"})
    except Exception:
        pass

    # 检查 soul_proposals 积压
    try:
        conn = _conn()
        soul_count = conn.execute(
            "SELECT COUNT(*) FROM soul_proposals WHERE status='pending'"
        ).fetchone()[0]
        conn.close()
        if soul_count >= 5:
            obs = (
                f"soul_proposals 积压 {soul_count} 条待审阅提议。"
                f"长期不审阅会导致有价值的灵魂演化被搁置。"
            )
            existing = list_critiques("open")
            if not any("soul" in c.get("title", "").lower() for c in existing):
                cid = create_critique(
                    title=f"SOUL 提议积压（{soul_count}条）",
                    observation=obs,
                    source="scan",
                    evidence=[f"soul_proposals 表当前有 {soul_count} 条 pending 提议"],
                    severity=2,
                    confidence=0.85,
                    scope="observation_only",
                )
                results.append({"id": cid, "title": f"SOUL 提议积压（{soul_count}条）"})
    except Exception:
        pass

    return results


# ── 用户负反馈触发（限流保护）──────────────────────────────────────────────────────

# 简单内存限流：session 级，24h 不重置（进程重启清零）
_user_signal_registry: dict[str, int] = {}  # session_id → count


def try_create_from_user_signal(
    observation: str,
    session_id: str | None,
    cfg: dict,
    recent_evidence: list[str] | None = None,
) -> int | None:
    """
    用户负反馈触发 critique，带限流：
    - 同一 session 最多 1 条
    - 24h 内同类不重复
    返回创建的 ID 或 None（被限流）
    """
    max_per_session = cfg.get("critique", {}).get("max_user_signal_per_session", 1)
    sid = session_id or "default"

    if _user_signal_registry.get(sid, 0) >= max_per_session:
        return None

    # 24h 内同类检查
    conn = _conn()
    cutoff = (datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds")
    existing = conn.execute(
        "SELECT COUNT(*) FROM self_critiques WHERE source='user_signal' AND created_at > ?",
        (cutoff,),
    ).fetchone()[0]
    conn.close()
    if existing > 0:
        return None

    if len(observation) < 30:
        observation = observation + "（用户反馈：回应与预期不符，需要进一步分析）"

    title = observation[:20] + "…" if len(observation) > 20 else observation
    cid = create_critique(
        title=title,
        observation=observation,
        source="user_signal",
        evidence=recent_evidence or [],
        session_id=session_id,
        severity=2,
        confidence=0.6,
        scope="observation_only",
    )
    _user_signal_registry[sid] = _user_signal_registry.get(sid, 0) + 1
    return cid
