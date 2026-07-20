import importlib


def test_control_plane_domain_packages_exist() -> None:
    expected_modules = [
        "atlas.db",
        "atlas.agents",
        "atlas.messages",
        "atlas.tasks",
        "atlas.events",
        "atlas.artifacts",
        "atlas.config_sync",
        "atlas.api",
        "atlas.adapters",
        "atlas.runtime",
    ]

    for module_name in expected_modules:
        assert importlib.import_module(module_name).__name__ == module_name
