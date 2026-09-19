"""Scanner drivers: each one turns a device (or a stand-in for one) into fragments."""

from __future__ import annotations

from collections.abc import Callable

from physical_ai_scanner.drivers.base import DeviceInfo, Driver, Fragment

DRIVERS: dict[str, Callable[..., Driver]] = {}


def register(name: str) -> Callable[[type[Driver]], type[Driver]]:
    def decorator(cls: type[Driver]) -> type[Driver]:
        DRIVERS[name] = cls
        return cls

    return decorator


def driver_for(name: str, **options: object) -> Driver:
    # Import on demand: a driver's dependency (an SDK) is only needed when it is asked for.
    if name not in DRIVERS:
        if name == "simulated":
            from physical_ai_scanner.drivers import simulated  # noqa: F401
        elif name == "folder":
            from physical_ai_scanner.drivers import folder  # noqa: F401
        elif name == "realsense":
            from physical_ai_scanner.drivers import realsense  # noqa: F401
    try:
        factory = DRIVERS[name]
    except KeyError:
        raise ValueError(
            f"no scanner driver named {name!r}; known: simulated, folder, realsense"
        ) from None
    return factory(**options)


__all__ = ["DRIVERS", "DeviceInfo", "Driver", "Fragment", "driver_for", "register"]
