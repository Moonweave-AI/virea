from scripts.doc_layout import format_document


def test_layout_preserves_technical_content_and_dated_metadata():
    document = """---
type: evidence
status: Historical
owner: VIREA maintainers
created: 2026-08-01
canonical: doc/research/example.md
---

# Original result

<a id="rotation-proof"></a>

$$R = AB$$

```python
matrix = parent @ local
```

| Result | Value |
|---|---|
| Error | 0.01 |
"""
    result = format_document(document, "doc/research/example.md")
    assert document.split("---\n", 2)[2].strip() in result
    assert "created: 2026-08-01" in result
    assert "status: Historical" in result
    assert result.index("# Original result") < result.index("type: evidence")
    assert format_document(result, "doc/research/example.md") == result


def test_layout_does_not_duplicate_existing_metadata_comments():
    document = """# A guide

A source example.

<!--
---
type: reference
canonical: doc/reference/example.md
---
-->
"""
    result = format_document(document, "doc/reference/example.md")
    assert result.count("canonical:") == 1
    assert result.count("BEGIN DOC NAV") == 1
    assert format_document(result, "doc/reference/example.md") == result


def test_navigation_resolves_from_nested_pages_in_both_languages():
    en = format_document("# Setup\n", "doc/getting-started/automatic-setup.en.md")
    zh = format_document("# 部署\n", "doc/getting-started/automatic-setup.zh-CN.md")
    assert "[✦ VIREA](../../README.md)" in en
    assert "[Demos](../demos/README.en.md)" in en
    assert "[简体中文](automatic-setup.zh-CN.md)" in en
    assert "[✦ VIREA](../../README.zh-CN.md)" in zh
    assert "[English](automatic-setup.en.md)" in zh
