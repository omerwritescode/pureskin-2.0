"""A rule, threshold or weight can't change without a config version bump.

Each profile stores the questionnaire and merge config versions it was scored with
(score_sources.version), so a changed value under an old version string would make
stored provenance lie. The ingredient, routine and recommendation configs follow the
same rule (routine responses report their versions).
When this test fails:
  1. bump the version string in the config file (e.g. merge-1.0.0 -> merge-1.1.0);
  2. add the new version with the fingerprint from the failure message to RECORDED.
Never edit a recorded fingerprint.
"""

import hashlib
import json
from types import ModuleType

import pytest

from app.services.catalog import catalog_config
from app.services.chat import chat_config
from app.services.ingredients import ingredient_config
from app.services.questionnaire import questionnaire_config
from app.services.recommendation import recommendation_config, routine_config
from app.services.skin_profile import skin_profile_config

RECORDED = {
    "questionnaire-1.0.0": "a228f50bd2e32cca",
    "merge-1.0.0": "7485d277d8b2e553",
    "ingredients-1.0.0": "4a94921f822ddff6",
    "routine-1.0.0": "08209916f5c2a19f",
    "routine-2.0.0": "cbf3b7f0e9dd5ac6",
    "ingredients-1.1.0": "dd1efb09be4f6242",
    "routine-2.1.0": "02df1ea245514a25",
    "routine-2.2.0": "74cb6b4aa47dadf4",
    "recommendation-1.0.0": "2c664808e8887a95",
    "ingredients-1.2.0": "6a51213d2fe604c6",
    "routine-2.3.0": "cac112506d014a46",
    "catalog-1.0.0": "7f4991367e8eabda",
    "recommendation-1.0.1": "a23ff72ea1e7fb2c",
    "chat-1.0.0": "c7a206c05a82f2de",
    "chat-1.1.0": "9bc62d71edf36867",
}

CONFIGS = [
    (questionnaire_config, "CONFIG_VERSION"),
    (skin_profile_config, "MERGE_CONFIG_VERSION"),
    (ingredient_config, "INGREDIENT_CONFIG_VERSION"),
    (routine_config, "ROUTINE_CONFIG_VERSION"),
    (recommendation_config, "RECOMMENDATION_CONFIG_VERSION"),
    (catalog_config, "CATALOG_CONFIG_VERSION"),
    (chat_config, "CHAT_CONFIG_VERSION"),
]


def _plain(value):
    """JSON-able, deterministic form (tuple dict keys become their repr)."""
    if isinstance(value, dict):
        return {(k if isinstance(k, str) else repr(k)): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def fingerprint(module: ModuleType, version_name: str) -> str:
    values = {
        name: _plain(getattr(module, name))
        for name in dir(module)
        if name.isupper() and name != version_name
    }
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()[:16]


@pytest.mark.parametrize(("module", "version_name"), CONFIGS, ids=lambda c: getattr(c, "__name__", c))
def test_config_values_change_only_with_a_version_bump(module, version_name):
    version = getattr(module, version_name)
    current = fingerprint(module, version_name)
    assert version in RECORDED, (
        f"{module.__name__}: new version {version!r}. Add {version!r}: {current!r} to RECORDED."
    )
    assert RECORDED[version] == current, (
        f"{module.__name__}: a value changed but {version_name} is still {version!r}. "
        f"Bump it, then add the new version with fingerprint {current!r} to RECORDED."
    )


def test_fingerprint_notices_a_change(monkeypatch):
    before = fingerprint(skin_profile_config, "MERGE_CONFIG_VERSION")
    monkeypatch.setattr(skin_profile_config, "ACNE_IMAGE_PULL", 0.3)
    assert fingerprint(skin_profile_config, "MERGE_CONFIG_VERSION") != before
