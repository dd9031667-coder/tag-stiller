from app.services.rename_templates import (
    DEFAULT_TEMPLATE_NAME, dump_template_mapping, load_template_mapping,
)
from app.services.renaming import DEFAULT_RENAME_TEMPLATE


def test_template_mapping_roundtrip():
    encoded = dump_template_mapping({
        "Короткий": "{track:02d} - {title}",
        "Артист": "{artist} - {title}",
    })
    loaded = load_template_mapping(encoded)
    assert loaded["Короткий"] == "{track:02d} - {title}"
    assert loaded["Артист"] == "{artist} - {title}"
    assert loaded[DEFAULT_TEMPLATE_NAME] == DEFAULT_RENAME_TEMPLATE


def test_invalid_template_storage_falls_back_to_default():
    assert load_template_mapping("not-json") == {
        DEFAULT_TEMPLATE_NAME: DEFAULT_RENAME_TEMPLATE,
    }


def test_empty_names_and_templates_are_not_saved():
    loaded = load_template_mapping(dump_template_mapping({
        "": "{title}",
        "Empty": "",
    }))
    assert loaded == {DEFAULT_TEMPLATE_NAME: DEFAULT_RENAME_TEMPLATE}
