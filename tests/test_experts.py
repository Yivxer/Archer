"""Expert workbench resolution tests."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.experts import (
    DEFAULT_EXPERTS,
    EXPERT_IDS,
    active_expert,
    active_expert_id,
    expert_memory_tags,
    expert_ids,
    expert_skill_allowlist,
    expert_starters,
    experts,
    filter_skills_for_expert,
    merge_expert_tags,
)
from skills.loader import load_skills


def test_builtin_experts_load_all_six():
    catalog = experts({})
    for expert_id in EXPERT_IDS:
        assert expert_id in catalog
    assert catalog["developer"]["label"] == "开发工程师"


def test_experts_merge_user_override():
    cfg = {
        "experts": {
            "developer": {
                "note": "自定义工程说明",
            }
        }
    }
    catalog = experts(cfg)
    assert catalog["developer"]["note"] == "自定义工程说明"
    assert catalog["developer"]["label"] == DEFAULT_EXPERTS["developer"]["label"]


def test_active_expert_defaults_to_default():
    assert active_expert_id({}) == "default"
    assert active_expert_id({"persona": {"current_expert": "missing"}}) == "default"
    assert active_expert_id({"persona": {"current_expert": "developer"}}) == "developer"


def test_default_expert_does_not_restrict_skills():
    all_skills = {"shell": object(), "hugo_blog": object(), "web_search": object()}
    expert = active_expert({})
    assert expert_skill_allowlist(expert) is None
    assert set(filter_skills_for_expert(all_skills, expert)) == set(all_skills)


def test_developer_allowlist_filters_to_engineering_pool():
    all_skills = load_skills()
    expert = experts({})["developer"]
    allowlist = expert_skill_allowlist(expert)
    scoped = filter_skills_for_expert(all_skills, expert)

    assert allowlist is not None
    assert "shell" in scoped
    assert "hugo_blog" not in scoped
    assert len(scoped) == len([name for name in allowlist if name in all_skills])
    assert len(scoped) >= 5


def test_counselor_allowlist_excludes_web_search():
    all_skills = load_skills()
    expert = experts({})["counselor"]
    scoped = filter_skills_for_expert(all_skills, expert)

    assert "web_search" not in scoped
    assert "memory_save" in scoped


def test_each_expert_has_four_starters():
    catalog = experts({})
    for expert_id in EXPERT_IDS:
        starters = expert_starters(catalog[expert_id])
        assert len(starters) == 4, expert_id
        assert all(item["label"] and item["prompt"] for item in starters)


def test_custom_expert_from_config():
    cfg = {
        "experts": {
            "my-coach": {
                "label": "我的教练",
                "note": "个人成长",
                "skill_policy": "allowlist",
                "skills": ["summarize"],
                "prompt_overlay": "教练工作台",
                "memory_tags": ["expert:my-coach"],
                "starters": ["帮我看看这周最想推进的一件事"],
            }
        }
    }
    catalog = experts(cfg)
    assert "my-coach" in catalog
    assert catalog["my-coach"]["label"] == "我的教练"
    assert expert_memory_tags(catalog["my-coach"]) == ["expert:my-coach"]
    assert expert_ids(cfg)[-1] == "my-coach"
    assert active_expert_id({"persona": {"current_expert": "my-coach"}, **cfg}) == "my-coach"


def test_merge_expert_tags_appends_primary_tag():
    expert = experts({})["parent-educator"]
    merged = merge_expert_tags("parenting", expert)
    assert "expert:parent-educator" in merged
    assert "parenting" in merged
