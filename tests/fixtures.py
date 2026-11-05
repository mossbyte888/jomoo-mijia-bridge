"""Synthetic frames: no device captures, addresses or household state."""
import importlib
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
pkg = types.ModuleType('public_test')
pkg.__path__ = [str(ROOT / 'custom_components/jomoo_local')]
sys.modules[pkg.__name__] = pkg
core = importlib.import_module('public_test.core')
ops = importlib.import_module('public_test.operations')
transport = importlib.import_module('public_test.transport')
identity = importlib.import_module('public_test.identity')


def frame(kind, size, values):
    raw = bytearray(size)
    raw[:6] = bytes([0xf3, 0xf4, size - 4, 0x21, 0, kind])
    raw[-1] = 0xfc
    for index, value in values.items():
        raw[index] = value
    raw[-2] = sum(raw[2:-2]) & 255
    return bytes(raw)


def capture(model):
    if model == 'sq9650':
        raw = bytearray(26)
        raw[0] = raw[-1] = 0xfc
        raw[2] = 1
        raw[6] = 0x30
        raw[1] = sum(raw[2:-1]) & 255
        return [bytes(raw)]
    return [frame(0xe2, 13, {10: 9}),
            frame(0xfa, 16, {7: 0x10, 8: 0x10, 9: 0x11, 10: 0x10, 13: 1}),
            frame(0xe9, 14, {9: 1}), frame(0xea, 11, {})]


def state(model):
    result = {}
    for raw in capture(model):
        result.update(core.parse(model, raw)[1])
    return result
