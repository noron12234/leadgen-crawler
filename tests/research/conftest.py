"""
Research tests — 需要網路連線的探索性測試，不在 CI 中執行。
使用 pytest -m research 或直接指定路徑來執行。
"""
import pytest


def pytest_collection_modifyitems(config, items):
    """自動標記 research/ 下的測試為 'research'"""
    for item in items:
        if "research" in str(item.fspath):
            item.add_marker(pytest.mark.research)
