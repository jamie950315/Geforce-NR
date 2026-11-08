"""Daily-launcher resolution and verified 310.9.16 runtime extensions without modifying the installed Core."""
from dataclasses import dataclass, is_dataclass, replace
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys


NR_HEIGHTS = (720, 900, 1080, 1440)
_WORK_BUDGETS = (540, *NR_HEIGHTS)
FLOW_WIDTHS = (320, 640, 960, 1280, 1600, 1920)
NR_RUNTIME_310_9_16_SHA256 = 'cdfa6c1ec784867182164c7836f324f087b5c9f374d0c9fe46f54999feabf3ed'
NR_RUNTIME_310_9_16_SIZE = 276162560
NR_MODEL_PRESETS = (0, 1, 2)


def verify_nr_runtime_310_9_16(root, preset=2):
    """Attest the isolated 310.9.16 neural runtime without replacing 310.8.SF.0 worker copies."""
    if type(preset) is not int or preset not in NR_MODEL_PRESETS:
        raise ValueError('NR model preset must be 0 (auto), 1 (original), or 2 (optimized)')
    root = Path(root)
    record_path = root / 'runtime-310.9.16.json'
    dll_path = root / 'runtime-310.9.16' / 'nvngx_dlssnr.dll'
    try:
        record = json.loads(record_path.read_text(encoding='utf-8-sig'))
        if (record.get('version') != '310.9.16.0'
                or record.get('runtime_sha256') != NR_RUNTIME_310_9_16_SHA256
                or record.get('size') != NR_RUNTIME_310_9_16_SIZE):
            raise RuntimeError('NR 310.9.16 runtime record mismatch')
        if dll_path.stat().st_size != NR_RUNTIME_310_9_16_SIZE:
            raise RuntimeError('NR 310.9.16 runtime size mismatch')
        with dll_path.open('rb') as handle:
            actual = hashlib.file_digest(handle, 'sha256').hexdigest()
        if actual != NR_RUNTIME_310_9_16_SHA256:
            raise RuntimeError('NR 310.9.16 runtime SHA256 mismatch')
    except (OSError, ValueError, KeyError) as exc:
        raise RuntimeError('Verified NR 310.9.16 runtime is unavailable; stage runtime-310.9.16 first.') from exc
    return dll_path, dict(version='310.9.16.0', runtime=str(dll_path),
                          runtime_sha256=NR_RUNTIME_310_9_16_SHA256,
                          size=NR_RUNTIME_310_9_16_SIZE, preset=preset)



def settings_type(base):
    """Retain every Core validation rule while admitting 1440p NR and 900p/1080p flow budgets."""
    if not is_dataclass(base) or not base.__dataclass_params__.frozen:
        raise TypeError('Core Settings must be a frozen dataclass')

    @dataclass(frozen=True)
    class DailySettings(base):
        def __post_init__(self):
            overrides = {}
            if type(self.nr_height) is int and self.nr_height == 1440:
                overrides['nr_height'] = 1080
            flow_w = getattr(self, 'flow_width', None)
            if type(flow_w) is int and flow_w in (1600, 1920):
                overrides['flow_width'] = 1280
            if overrides:
                # A separate validation-only value exercises Core's entire
                # contract. The actual immutable settings retain the extended values.
                replace(self, **overrides)
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


def flow_size(width, height, input_width):
    """Core's even-size, aspect-preserving flow rule with 900p and 1080p budgets."""
    if (type(width) is not int or type(height) is not int
            or not 64 <= width <= 7680 or not 64 <= height <= 4320):
        raise ValueError('Unsupported source dimensions')
    if type(input_width) is not int or input_width not in FLOW_WIDTHS:
        raise ValueError('Unsupported flow input width')
    scale = min(1.0, input_width / width, (input_width * 9 / 16) / height)
    return max(128, int(width * scale) // 2 * 2), max(128, int(height * scale) // 2 * 2)


def load_engine(Settings):
    """Execute the unchanged Core source in a separate daily-only namespace."""
    name = 'gfn_core.daily_engine'
    existing = sys.modules.get(name)
    if existing is not None:
        if (getattr(existing, '_daily_processing_extension', False)
                and existing.Settings is Settings and existing.work_size is work_size
                and getattr(existing, 'flow_size', flow_size) is flow_size):
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
        orig_transport = getattr(module, 'Transport', None)
        if orig_transport is not None:
            def daily_transport(cmd, cwd, env, log, _orig=orig_transport):
                runtime_dll = os.environ.get('GFN_NR_RUNTIME_DLL')
                if runtime_dll:
                    env = dict(env)
                    env['NS_NR_DLL'] = runtime_dll
                    env['NS_NR_PRESET'] = os.environ.get('GFN_NR_MODEL_PRESET', '2')
                return _orig(cmd, cwd, env, log)
            module.Transport = daily_transport
        module.Settings = Settings
        module.work_size = work_size
        module.flow_size = flow_size
        module._daily_processing_extension = True
        return module.Engine
    except BaseException:
        if sys.modules.get(name) is module:
            del sys.modules[name]
        raise
