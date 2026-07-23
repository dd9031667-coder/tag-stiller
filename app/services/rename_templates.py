from __future__ import annotations

import json

from app.services.renaming import DEFAULT_RENAME_TEMPLATE


DEFAULT_TEMPLATE_NAME = "По умолчанию"


def load_template_mapping(raw: str | None) -> dict[str, str]:
    templates: dict[str, str] = {
        DEFAULT_TEMPLATE_NAME: DEFAULT_RENAME_TEMPLATE,
    }
    if not raw:
        return templates
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return templates
    if isinstance(payload, dict):
        for name, template in payload.items():
            clean_name = str(name).strip()
            clean_template = str(template).strip()
            if clean_name and clean_template and clean_name != DEFAULT_TEMPLATE_NAME:
                templates[clean_name] = clean_template
    return templates


def dump_template_mapping(templates: dict[str, str]) -> str:
    normalized = {
        DEFAULT_TEMPLATE_NAME: DEFAULT_RENAME_TEMPLATE,
        **{
            str(name).strip(): str(template).strip()
            for name, template in templates.items()
            if str(name).strip()
            and str(template).strip()
            and str(name).strip() != DEFAULT_TEMPLATE_NAME
        },
    }
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True)
