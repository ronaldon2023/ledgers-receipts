import importlib


def test_packages_import() -> None:
    for name in ("bakery", "claims", "render", "receipts"):
        importlib.import_module(name)
