"""Daily-only settings and module-isolation contracts."""
from dataclasses import asdict, dataclass, FrozenInstanceError, replace
import importlib.util
import math
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch

from processing_support import NR_HEIGHTS, load_engine, settings_type, work_size


@dataclass(frozen=True)
class CoreSettingsFixture:
    nr_height: int = 720
    fps: int = 120
    bypass: bool = False

    def __post_init__(self):
        if type(self.nr_height) is not int or self.nr_height not in (540,720,900,1080):
            raise ValueError('nr_height')
        if type(self.fps) is not int or self.fps not in (60,120):
            raise ValueError('fps')
        if type(self.bypass) is not bool:
            raise ValueError('bypass')

    @property
    def min_free_mib(self):
        return int(math.ceil((1536+1536*(self.nr_height/720)**2)/256)*256)

    def to_dict(self):
        return asdict(self)


class ProcessingTests(unittest.TestCase):
    def test_1440_settings_stay_frozen_and_survive_replace(self):
        Settings=settings_type(CoreSettingsFixture)
        current=Settings(nr_height=1440)
        self.assertEqual(current.nr_height,1440)
        self.assertEqual(current.min_free_mib,7680)
        self.assertEqual(current.to_dict()['nr_height'],1440)
        changed=replace(current,bypass=True)
        self.assertIs(type(changed),Settings)
        self.assertEqual(changed.nr_height,1440)
        self.assertTrue(changed.bypass)
        with self.assertRaises(FrozenInstanceError):
            current.nr_height=1080
        with self.assertRaises(ValueError):
            CoreSettingsFixture(nr_height=1440)

    def test_1440_does_not_bypass_other_core_validation(self):
        Settings=settings_type(CoreSettingsFixture)
        for args in ({'nr_height':1440,'fps':1},{'nr_height':1440,'bypass':1},
                     {'nr_height':True},{'nr_height':1440.0},{'nr_height':2160}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                Settings(**args)
        self.assertEqual(Settings(nr_height=540).nr_height,540)

    def test_work_geometry_matches_core_and_adds_full_1440(self):
        self.assertEqual(NR_HEIGHTS,(720,900,1080,1440))
        for budget,expected in ((540,(960,540)),(720,(1280,720)),(900,(1600,900)),
                                (1080,(1920,1080)),(1440,(2560,1440))):
            self.assertEqual(work_size(2560,1440,budget),expected)
        self.assertEqual(work_size(1920,1080,1440),(1920,1080))
        self.assertEqual(work_size(3440,1440,1440),(2560,1070))
        self.assertEqual(work_size(1080,1920,1440),(810,1440))
        self.assertEqual(work_size(641,481,1440),(640,480))
        self.assertEqual(work_size(7680,4320,1440),(2560,1440))
        self.assertEqual(work_size(64,4320,540),(64,540))

    def test_geometry_rejects_bool_noninteger_and_out_of_bounds(self):
        for values in ((True,720,720),(1280,False,720),(1280,720,True),
                       (1280,720,1440.0),(63,720,720),(7681,720,720),
                       (1280,4321,720),(1280,720,2160)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                work_size(*values)

    def test_loader_keeps_original_module_and_core_files_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'engine.py'
            source='''from gfn_core.config import Settings, work_size
class Engine:
    def configure(self):
        return Settings(nr_height=1440), work_size(2560,1440,1440)
'''
            path.write_text(source)
            package=ModuleType('gfn_core');package.__path__=[folder]
            config=ModuleType('gfn_core.config')
            config.Settings=CoreSettingsFixture
            config.work_size=lambda *args: 'original'
            original=ModuleType('gfn_core.engine')
            original.__spec__=importlib.util.spec_from_file_location('gfn_core.engine',path)
            original.Settings=config.Settings;original.work_size=config.work_size
            Settings=settings_type(CoreSettingsFixture)
            with patch.dict(sys.modules,{'gfn_core':package,'gfn_core.config':config,'gfn_core.engine':original}):
                sys.modules.pop('gfn_core.daily_engine',None)
                Engine=load_engine(Settings)
                settings,geometry=Engine().configure()
                self.assertEqual(settings.nr_height,1440)
                self.assertEqual(geometry,(2560,1440))
                self.assertEqual(Engine.__module__,'gfn_core.daily_engine')
                self.assertIs(load_engine(Settings),Engine)
                self.assertIs(original.Settings,CoreSettingsFixture)
                self.assertIs(original.work_size,config.work_size)
                with self.assertRaisesRegex(RuntimeError,'already owned'):
                    load_engine(settings_type(CoreSettingsFixture))
            self.assertEqual(path.read_text(),source)
            self.assertEqual([p.name for p in Path(folder).iterdir()],['engine.py'])

    @unittest.skipUnless(sys.platform=='win32','Actual Core dependency check is Windows-only')
    def test_installed_core_settings_when_available(self):
        try:
            from gfn_core.config import Settings as CoreSettings
        except ImportError:
            self.skipTest('Core is not available in this Python environment')
        Settings=settings_type(CoreSettings)
        settings=Settings(nr_height=1440)
        self.assertEqual(settings.min_free_mib,7680)
        self.assertEqual(replace(settings,bypass=True).nr_height,1440)
        with self.assertRaises(ValueError):
            CoreSettings(nr_height=1440)


if __name__=='__main__':
    unittest.main()
