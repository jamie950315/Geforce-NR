import math
import unittest
from hdr_color_reference import luminance, proxy_gamut, limit_edit
from daily_backend import DEFAULTS, migrate_settings, validated


class ColorTests(unittest.TestCase):
    def test_positive_inputs_are_unchanged(self):
        for rgb in ((0,0,0),(.18,.18,.18),(1,2,10),(65504,400,1)):
            self.assertEqual(proxy_gamut(rgb),rgb)

    def test_negative_gamut_preserves_luminance_and_direction(self):
        for rgb in ((-.2,2,7),(2,-.1,1),(-10,3,20)):
            y=luminance(rgb)
            result=proxy_gamut(rgb)
            self.assertGreater(y,0)
            self.assertGreaterEqual(min(result),0)
            self.assertAlmostEqual(luminance(result),y,places=12)
            scales=[(v-y)/(x-y) for x,v in zip(rgb,result) if abs(x-y)>1e-9]
            self.assertLess(max(scales)-min(scales),1e-12)
            self.assertGreater(luminance(tuple(max(x,0) for x in rgb)),y)

    def test_nonpositive_luminance_maps_to_black_proxy(self):
        self.assertEqual(proxy_gamut((-2,-1,1)),(0,0,0))

    def test_edit_limiter_preserves_direction_and_bound(self):
        delta=(.6,.3,-.2)
        result=limit_edit(delta)
        scales=[a/b for a,b in zip(result,delta)]
        self.assertAlmostEqual(max(scales),min(scales))
        self.assertEqual(max(abs(x) for x in result),.25)
        legacy=tuple(max(-.25,min(.25,x)) for x in delta)
        self.assertNotAlmostEqual(legacy[0]/delta[0],legacy[1]/delta[1])
        for value in ((0,0,0),(.1,-.2,.25)):
            self.assertEqual(limit_edit(value),value)

    def test_nonfinite_input_rejected(self):
        for fn in (proxy_gamut,limit_edit):
            with self.assertRaises(ValueError):fn((math.nan,1,2))

    def test_existing_preferences_keep_legacy_mapping(self):
        old=dict(DEFAULTS,hdr=True)
        old.pop('hdr_mapping')
        self.assertEqual(migrate_settings(old),dict(old,hdr_mapping='legacy'))
        with self.assertRaises(ValueError):validated(dict(DEFAULTS,hdr_mapping='unknown'))


if __name__=='__main__':
    unittest.main()
