from dataclasses import dataclass


@dataclass(frozen=True)
class CachePolicy:
    tool_draft_ttl_seconds: int = 30 * 60
    tool_result_ttl_seconds: int = 10 * 60
    tool_fingerprint_result_ttl_seconds: int = 10 * 60
    vault_focus_sensor_ttl_seconds: int = 10 * 60
    vault_focus_mtime_ttl_seconds: int = 5 * 60
    model_response_cache_enabled: bool = False


CACHE_POLICY = CachePolicy()


def cache_policy_summary() -> str:
    return (
        f"tool_draft={CACHE_POLICY.tool_draft_ttl_seconds}s, "
        f"tool_result={CACHE_POLICY.tool_result_ttl_seconds}s, "
        f"tool_fingerprint={CACHE_POLICY.tool_fingerprint_result_ttl_seconds}s, "
        f"vault_focus_sensor={CACHE_POLICY.vault_focus_sensor_ttl_seconds}s, "
        f"vault_focus_mtime={CACHE_POLICY.vault_focus_mtime_ttl_seconds}s, "
        f"model_response={'enabled' if CACHE_POLICY.model_response_cache_enabled else 'disabled'}"
    )
