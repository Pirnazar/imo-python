"""64-bit account identifier used by IMO Web's media service."""
from __future__ import annotations

from struct import unpack_from


_MASK = (1 << 64) - 1
_K0 = 0xC3A5C85C97CB3127
_K1 = 0xB492B66FBE98F273
_K2 = 0x9AE16A3B2F90404F
_K_MIX = 0x9DDFEA08EB382D69


def _rotate(value, shift):
    value &= _MASK
    return (value >> shift) | ((value << (64 - shift)) & _MASK)


def _shift_mix(value):
    value &= _MASK
    return value ^ (value >> 47)


def _multiply(left, right):
    # The browser computes 16-bit limbs and truncates each carry to 32 bits
    # before shifting. A native CityHash64 multiplication can yield another ID.
    a, b, c, d = ((left >> shift) & 0xFFFF for shift in (0, 16, 32, 48))
    e, f, g, h = ((right >> shift) & 0xFFFF for shift in (0, 16, 32, 48))
    low = a * e
    mid = (low >> 16) + b * e + a * f
    high = ((mid & 0xFFFFFFFF) >> 16) + c * e + b * f + a * g
    top = ((high & 0xFFFFFFFF) >> 16) + d * e + c * f + b * g + a * h
    return ((top & 0xFFFF) << 48 | (high & 0xFFFF) << 32 |
            (mid & 0xFFFF) << 16 | (low & 0xFFFF))


def _mix(left, right, multiplier=_K_MIX):
    first = _shift_mix(_multiply(left ^ right, multiplier))
    second = _shift_mix(_multiply(right ^ first, multiplier))
    return _multiply(second, multiplier)


def _swap_bytes(value):
    return int.from_bytes((value & _MASK).to_bytes(8, "little"), "big")


def _weak(data, offset, left, right):
    a, b, c, d = unpack_from("<4Q", data, offset)
    left += a
    right = _rotate(right + left + d, 21) + left
    left += b + c
    return (left + d) & _MASK, (right + _rotate(left, 44)) & _MASK


def _hash(data):
    size = len(data)
    multiplier = _K2 + size * 2

    def fetch(offset):
        return unpack_from("<Q", data, offset)[0]

    if size <= 3:
        if not size:
            return _K2
        a = data[0] + (data[size // 2] << 8)
        b = size + (data[-1] << 2)
        return _multiply(_shift_mix(_multiply(a, _K2) ^ _multiply(b, _K0)), _K2)
    if size <= 7:
        a = unpack_from("<I", data)[0]
        b = unpack_from("<I", data, size - 4)[0]
        return _mix(size + (a << 3), b, multiplier)
    if size <= 16:
        a, b = fetch(0) + _K2, fetch(size - 8)
        return _mix(_multiply(_rotate(b, 37), multiplier) + a,
                    _multiply(_rotate(a, 25) + b, multiplier), multiplier)
    if size <= 32:
        a, b = _multiply(fetch(0), _K1), fetch(8)
        c, d = _multiply(fetch(size - 8), multiplier), _multiply(fetch(size - 16), _K2)
        return _mix(_rotate(a + b, 43) + _rotate(c, 30) + d,
                    a + _rotate(b + _K2, 18) + c, multiplier)
    if size <= 64:
        a, b = _multiply(fetch(0), _K2), fetch(8)
        c, d = fetch(size - 24), fetch(size - 32)
        e, f = _multiply(fetch(16), _K2), _multiply(fetch(24), 9)
        g, h = fetch(size - 8), _multiply(fetch(size - 16), multiplier)
        u = _rotate(a + g, 43) + _multiply(_rotate(b, 30) + c, 9)
        v = ((a + g) & _MASK ^ d) + f + 1
        w = _swap_bytes(_multiply(u + v, multiplier)) + h
        x = _rotate(e + f, 42) + c
        y = _multiply(_swap_bytes(_multiply(v + w, multiplier)) + g, multiplier)
        z = e + f + c
        a = _swap_bytes(_multiply(x + z, multiplier) + y) + b
        b = _multiply(_shift_mix(_multiply(z + a, multiplier) + d + h), multiplier)
        return (b + x) & _MASK

    x = fetch(size - 40)
    y = (fetch(size - 16) + fetch(size - 56)) & _MASK
    z = _mix(fetch(size - 48) + size, fetch(size - 24))
    v = _weak(data, size - 64, size, z)
    w = _weak(data, size - 32, y + _K1, x)
    x = (_multiply(x, _K1) + fetch(0)) & _MASK
    for offset in range(0, (size - 1) & ~63, 64):
        x = _multiply(_rotate(x + y + v[0] + fetch(offset + 8), 37), _K1)
        y = _multiply(_rotate(y + v[1] + fetch(offset + 48), 42), _K1)
        x ^= w[1]
        y = (y + v[0] + fetch(offset + 40)) & _MASK
        z = _multiply(_rotate(z + w[0], 33), _K1)
        v = _weak(data, offset, _multiply(v[1], _K1), x + w[0])
        w = _weak(data, offset + 32, z + w[1], y + fetch(offset + 16))
        x, z = z, x
    return _mix(_mix(v[0], w[0]) + _multiply(_shift_mix(y), _K1) + z, _mix(v[1], w[1]) + x)


def account_hash(uid: str) -> int:
    value = _hash(uid.encode("utf-8"))
    return min(value, (1 << 64) - value)
