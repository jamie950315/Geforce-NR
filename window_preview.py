"""Capture a visible selected window rectangle as an in-memory SDR PPM."""
import ctypes
from ctypes import wintypes as wt
import os


def capture_rectangle(x, y, width, height):
    if os.name != 'nt':
        raise RuntimeError('Window preview requires Windows')
    u = ctypes.WinDLL('user32', use_last_error=True)
    g = ctypes.WinDLL('gdi32', use_last_error=True)
    u.GetDC.argtypes = [wt.HWND]; u.GetDC.restype = wt.HDC
    u.ReleaseDC.argtypes = [wt.HWND, wt.HDC]; u.ReleaseDC.restype = ctypes.c_int
    u.GetSystemMetrics.argtypes = [ctypes.c_int]; u.GetSystemMetrics.restype = ctypes.c_int
    g.CreateCompatibleDC.argtypes = [wt.HDC]; g.CreateCompatibleDC.restype = wt.HDC
    g.CreateDIBSection.argtypes = [wt.HDC, ctypes.c_void_p, wt.UINT, ctypes.POINTER(ctypes.c_void_p), wt.HANDLE, wt.DWORD]
    g.CreateDIBSection.restype = wt.HANDLE
    g.SelectObject.argtypes = [wt.HDC, wt.HANDLE]; g.SelectObject.restype = wt.HANDLE
    g.DeleteObject.argtypes = [wt.HANDLE]; g.DeleteObject.restype = wt.BOOL
    g.DeleteDC.argtypes = [wt.HDC]; g.DeleteDC.restype = wt.BOOL
    g.BitBlt.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                        wt.HDC, ctypes.c_int, ctypes.c_int, wt.DWORD]
    g.BitBlt.restype = wt.BOOL
    g.GdiFlush.argtypes = []; g.GdiFlush.restype = wt.BOOL
    vx, vy, vw, vh = (u.GetSystemMetrics(i) for i in (76, 77, 78, 79))
    if not (64 <= width <= 7680 and 64 <= height <= 4320 and vx <= x and vy <= y
            and x+width <= vx+vw and y+height <= vy+vh):
        raise ValueError('Restore the entire game window on screen before drawing a mask')

    class Header(ctypes.Structure):
        _fields_ = [('size', wt.DWORD), ('width', wt.LONG), ('height', wt.LONG),
                    ('planes', wt.WORD), ('bits', wt.WORD), ('compression', wt.DWORD),
                    ('image_size', wt.DWORD), ('xppm', wt.LONG), ('yppm', wt.LONG),
                    ('used', wt.DWORD), ('important', wt.DWORD)]

    screen = u.GetDC(None)
    memory = bitmap = old = None
    if not screen:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        memory = g.CreateCompatibleDC(screen)
        header = Header(ctypes.sizeof(Header), width, -height, 1, 32, 0, width*height*4, 0, 0, 0, 0)
        bits = ctypes.c_void_p()
        bitmap = g.CreateDIBSection(screen, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
        if not memory or not bitmap or not bits:
            raise ctypes.WinError(ctypes.get_last_error())
        old = g.SelectObject(memory, bitmap)
        if not old or old == ctypes.c_void_p(-1).value:
            old = None
            raise RuntimeError('Could not select the preview bitmap')
        if not g.BitBlt(memory, 0, 0, width, height, screen, x, y, 0x00CC0020 | 0x40000000):
            raise ctypes.WinError(ctypes.get_last_error())
        if not g.GdiFlush():
            raise RuntimeError('Could not complete the preview capture')
        bgra = ctypes.string_at(bits, width*height*4)
        rgb = bytearray(width*height*3)
        rgb[0::3], rgb[1::3], rgb[2::3] = bgra[2::4], bgra[1::4], bgra[0::4]
        return f'P6\n{width} {height}\n255\n'.encode('ascii') + rgb
    finally:
        if old and memory:
            g.SelectObject(memory, old)
        if bitmap:
            g.DeleteObject(bitmap)
        if memory:
            g.DeleteDC(memory)
        u.ReleaseDC(None, screen)
