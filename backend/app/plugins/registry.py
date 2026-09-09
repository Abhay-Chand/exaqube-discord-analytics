"""
Discovery: directory scan + decorator, chosen over setuptools entry points.

Why a directory scan over entry points: entry points earn their keep when
plugins ship as separately-versioned, separately-installed packages (a
plugin marketplace, third-party extensions installed via pip). We have
neither here — every plugin lives in this one repo, in this one package,
deployed as one container. A directory scan gets the same "drop a file in,
it's picked up" property with zero packaging ceremony: no setup.py entry
point to register, no reinstall step, no import-time indirection to debug.
If this ever became a multi-package plugin ecosystem, entry_points would be
the right call — it isn't that, yet.

Why a decorator over pure scan-and-introspect: the decorator is what
actually puts a class in the registry; the scan's only job is to *import*
every module in this package so the decorators run. This keeps registration
explicit (grep-able: `@register_plugin` marks every tool the agent has) and
means a plugin module can contain private helper classes without them
accidentally being treated as tools.
"""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

from app.plugins.base import Plugin

_REGISTRY: dict[str, Plugin] = {}


def register_plugin(cls: type[Plugin]) -> type[Plugin]:
    instance = cls()
    if not getattr(instance, "name", None):
        raise ValueError(f"Plugin {cls.__name__} must define a non-empty `name`")
    if instance.name in _REGISTRY:
        raise ValueError(f"Duplicate plugin name '{instance.name}' ({cls.__name__})")
    _REGISTRY[instance.name] = instance
    return cls


def discover_plugins() -> dict[str, Plugin]:
    """Import every module under app/plugins/ (except base.py/registry.py)
    so their @register_plugin decorators fire. Call once at startup."""
    package_dir = Path(__file__).parent
    package_name = __name__.rsplit(".", 1)[0]  # "app.plugins"
    for module_info in pkgutil.iter_modules([str(package_dir)]):
        if module_info.name in ("base", "registry"):
            continue
        importlib.import_module(f"{package_name}.{module_info.name}")
    return dict(_REGISTRY)


def get_registry() -> dict[str, Plugin]:
    return dict(_REGISTRY)


def get_plugin(name: str) -> Plugin | None:
    return _REGISTRY.get(name)
