from polyvoice.hooks.stop import code_ratio, strip_markdown


def test_strip_markdown_removes_code_and_links() -> None:
    text = "## Done\nSee [docs](https://example.test).\n```python\nprint('x')\n```"
    assert strip_markdown(text) == "Done See docs."


def test_code_ratio_detects_symbol_heavy_text() -> None:
    assert code_ratio("def f(x): return x + 1") < 0.4
    assert code_ratio("{{{{{{{{{{{{{{{{{{{{") > 0.4
