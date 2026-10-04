"""Test docs site structure."""
from pathlib import Path


def test_docs_exist():
    base = Path('docs')
    assert (base / 'index.md').exists()
    assert (base / 'getting-started.md').exists()


def test_mkdocs_exists():
    assert Path('mkdocs.yml').exists()
