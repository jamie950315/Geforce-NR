"""Daily-launcher resolution extensions without modifying the installed Core."""
from dataclasses import dataclass, is_dataclass, replace
import importlib.util
import sys


NR_HEIGHTS = (720, 900, 1080, 1440)
_WORK_BUDGETS = (540, *NR_HEIGHTS)


def settings_type(base):
    """Retain every Core validation rule while admitting the 1440p NR budget."""
    if not is_dataclass(base) or not base.__dataclass_params__.frozen:
        raise TypeError('Core Settings must be a frozen dataclass')

    @dataclass(frozen=True)
    class DailySettings(base):
        def __post_init__(self):
            if type(self.nr_height) is int and self.nr_height == 1440:
                # A separate validation-only value exercises Core's entire
                # contract. The actual immutable settings retain NR1440.
                replace(self, nr_height=1080)
            else:
                base.__post_init__(self)

    return DailySettings


def work_size(width, height, budget):
    """Core's even-size, aspect-preserving rule with an additional 1440 budget."""
    if (type(width) is not int or type(height) is not int
            or not 64 <= width <= 7680 or not 64 <= height <= 4320):
        raise ValueError('Unsupported source dimensions')
    if type(budget) is not int or budget not in _WORK_BUDGETS:
        raise ValueError('Unsupported NR height budget')
    scale = min(1.0, budget / height, (budget * 16 / 9) / width)
    return max(64, int(width * scale) // 2 * 2), max(64, int(height * scale) // 2 * 2)


def load_engine(Settings):
    """Execute the unchanged Core source in a separate daily-only namespace."""
    name = 'gfn_core.daily_engine'
    existing = sys.modules.get(name)
    if existing is not None:
        if (getattr(existing, '_daily_processing_extension', False)
                and existing.Settings is Settings and existing.work_size is work_size):
            return existing.Engine
        raise RuntimeError('The daily engine namespace is already owned by another configuration')
    original = importlib.util.find_spec('gfn_core.engine')
    if original is None or original.origin is None:
        raise ImportError('Core engine source is unavailable')
    spec = importlib.util.spec_from_file_location(name, original.origin)
    if spec is None or spec.loader is None or not hasattr(spec.loader, 'get_source'):
        raise ImportError('Core engine must expose a Python source loader')
    source = spec.loader.get_source(name)
    if source is None:
        raise ImportError('Core engine Python source is unavailable')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        # Compiling the returned source avoids creating/replacing Core's .pyc.
        # Imports and relative package resolution still use the original spec.
        exec(compile(source, original.origin, 'exec'), module.__dict__)
        module.Settings = Settings
        module.work_size = work_size
        module._daily_processing_extension = True
        return module.Engine
    except BaseException:
        if sys.modules.get(name) is module:
            del sys.modules[name]
        raise
