"""Wire contract version helpers shared by FastAPI and legacy adapters."""
from __future__ import annotations


CONTRACT_VERSION = 1
CONTRACT_VERSION_HEADER = "X-Archer-Contract-Version"


def versioned_dict(payload: dict) -> dict:
    result = dict(payload)
    result["contractVersion"] = CONTRACT_VERSION
    return result


def versioned_payload(payload: dict | list) -> dict:
    if isinstance(payload, list):
        return {
            "contractVersion": CONTRACT_VERSION,
            "data": payload,
        }
    return versioned_dict(payload)
