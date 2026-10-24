"""知乎搜索接口签名适配。

签名实现来自 MediaCrawler 的学习版知乎适配，保留其原始版权与许可证声明；
这里仅负责在 CreatorHub 内调用，不把签名算法散落到抓取流程中。
"""
from __future__ import annotations

import hashlib
import re
import secrets
from pathlib import Path


_JS_PATH = Path(__file__).parent / "static" / "zhihu.js"
_INIT_STR = "6fpLRqJO8M/c3jnYxFkUVC4ZIG12SiH=5v0mXDazWBTsuw7QetbKdoPyAl+hN9rgE"
_MASK = 0xFFFFFFFF
_TABLES: tuple[tuple[int, ...], tuple[int, ...]] | None = None
_AVAILABLE: bool | None = None


def _tables() -> tuple[tuple[int, ...], tuple[int, ...]]:
    global _TABLES
    if _TABLES is not None:
        return _TABLES
    source = (_JS_PATH.read_text(encoding="utf-8-sig"))
    def read(name: str) -> tuple[int, ...]:
        match = re.search(rf"{name}:\s*\[([^\]]+)\]", source)
        if not match:
            raise RuntimeError(f"知乎签名表缺失: {name}")
        return tuple(int(part.strip()) for part in match.group(1).split(","))
    _TABLES = (read("zk"), read("zb"))
    return _TABLES


def _u32(value: int) -> int:
    return value & _MASK


def _rol(value: int, bits: int) -> int:
    value = _u32(value)
    return _u32((value << bits) | (value >> (32 - bits)))


def _bytes4(value: int) -> list[int]:
    value = _u32(value)
    return [
        (value >> 24) & 0xFF,
        (value >> 16) & 0xFF,
        (value >> 8) & 0xFF,
        value & 0xFF,
    ]


def _word(data: list[int], offset: int) -> int:
    return _u32(
        (data[offset] << 24)
        | (data[offset + 1] << 16)
        | (data[offset + 2] << 8)
        | data[offset + 3]
    )


def _substitute(value: int, zb: tuple[int, ...]) -> int:
    data = _bytes4(value)
    substituted = [zb[byte] for byte in data]
    result = _word(substituted, 0)
    return _u32(result ^ _rol(result, 2) ^ _rol(result, 10)
                ^ _rol(result, 18) ^ _rol(result, 24))


def _array_0_16(data: list[int], zk: tuple[int, ...]) -> list[int]:
    words = [0] * 36
    words[0] = _word(data, 0)
    words[1] = _word(data, 4)
    words[2] = _word(data, 8)
    words[3] = _word(data, 12)
    for index in range(32):
        transformed = _substitute(
            words[index + 1] ^ words[index + 2] ^ words[index + 3] ^ zk[index],
            _tables()[1])
        words[index + 4] = _u32(words[index] ^ transformed)
    result: list[int] = []
    for index in (35, 34, 33, 32):
        result.extend(_bytes4(words[index]))
    return result


def _array_16_48(data: list[int], initial: list[int], zk: tuple[int, ...]) -> list[int]:
    result: list[int] = []
    for offset in range(0, len(data), 16):
        block = [_u32(data[offset + index] ^ initial[index]) for index in range(16)]
        initial = _array_0_16(block, zk)
        result.extend(initial)
    return result


def _encode_0_16(data: list[int], zk: tuple[int, ...]) -> list[int]:
    offsets = [48, 53, 57, 48, 53, 51, 102, 55,
               100, 49, 53, 101, 48, 49, 100, 55]
    return _array_0_16(
        [(value ^ offsets[index]) ^ 42 for index, value in enumerate(data)], zk)


def _encode(data: list[int]) -> list[int]:
    value = data[0] | (data[1] << 8) | (data[2] << 16)
    result = [value & 63]
    shift = 6
    while len(result) < 4:
        result.append((value >> shift) & 63)
        shift += 6
    return result


def _zse_96(md5_value: str) -> str:
    zk, _ = _tables()
    initial = [ord(char) for char in md5_value]
    initial.insert(0, 0)
    initial.insert(0, secrets.randbelow(127))
    initial.extend([14] * (48 - len(initial)))
    encoded = _encode_0_16(initial[:16], zk) + _array_16_48(initial[16:48],
                                                            _encode_0_16(initial[:16], zk), zk)
    encoded = list(encoded)
    for index in range(47, -1, -4):
        encoded[index] ^= 58
    encoded.reverse()
    result = []
    for offset in range(0, len(encoded), 3):
        result.extend(_encode(encoded[offset:offset + 3]))
    return "2.0_" + "".join(_INIT_STR[index] for index in result)


def available() -> bool:
    """返回签名运行时是否可用，不发起网络请求。"""
    global _AVAILABLE
    if _AVAILABLE is not None:
        return _AVAILABLE
    try:
        _AVAILABLE = bool(sign("/api/v4/search_v3?q=test", "d_c0=test"))
    except Exception:
        _AVAILABLE = False
    return _AVAILABLE


def sign(url: str, cookies: str) -> dict[str, str]:
    """为知乎 v4 API 生成 ``x-zse-96`` 与 ``x-zst-81``。"""
    cookie_text = str(cookies or "").strip()
    if not cookie_text:
        raise ValueError("知乎签名需要 Cookie")
    match = re.search(r"(?:^|;\s*)d_c0=([^;]+)", cookie_text)
    if not match:
        raise ValueError("知乎签名需要 d_c0 Cookie")
    token = "3_2.0aR_sn77yn6O92wOB8hPZnQr0EMYxc4f18wNBUgpTQ6nxERFZfTY0-4Lm-h3_tufIwJS8gcxTgJS_AuPZNcXCTwxI78YxEM20s4PGDwN8gGcYAupMWufIoLVqr4gxrRPOI0cY7HL8qun9g93mFukyigcmebS_FwOYPRP0E4rZUrN9DDom3hnynAUMnAVPF_PhaueTFH9fQL39OCCqYTxfb0rfi9wfPhSM6vxGDJo_rBHpQGNmBBLqPJHK2_w8C9eTVMO9Z9NOrMtfhGH_DgpM-BNM1DOxScLG3gg1Hre1FCXKQcXKkrSL1r9GWDXMk8wqBLNmbRH96BtOFqVZ7UYG3gC8D9cMS7Y9UrHLVCLZPJO8_CL_6GNCOg_zhJS8PbXmGTcBpgxfkieOPhNfthtf2gC_qD3YOce8nCwG2uwBOqeMoML9NBC1xb9yk6SuJhHLK7SM6LVfCve_3vLKlqcL6TxL_UosDvHLxrHmWgxBQ8Xs"
    md5_value = hashlib.md5(
        "+".join(("101_3_3.0", str(url), match.group(1), token)).encode()
    ).hexdigest()
    return {"x-zst-81": token, "x-zse-96": _zse_96(md5_value)}
