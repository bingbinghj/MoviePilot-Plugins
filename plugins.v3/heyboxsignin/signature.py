"""Web request signing ported from yowiv08/heybox at 15f7fb8."""

import hashlib
import secrets
import time


def make_web_hkey(path: str, time_sec: int, nonce: str) -> str:
    """Match the upstream Web hkey calculation including its four-byte mix."""
    alphabet = "AB45STUVWZEFGJ6CH01D237IXYPQRKLMN89"

    def remap(value, symbols):
        return "".join(symbols[ord(char) % len(symbols)] for char in str(value))

    def mul2(value):
        return ((value << 1) ^ 27) & 255 if value & 128 else value << 1

    def mix_x(value):
        return mul2(value) ^ value

    def mix_k(value):
        return mix_x(mul2(value))

    def mix_c(value):
        return mix_k(mix_x(mul2(value)))

    def mix_s(value):
        return mix_c(value) ^ mix_k(value) ^ mix_x(value)

    normalized = "/" + "/".join(part for part in path.split("/") if part) + "/"
    parts = [remap(time_sec, alphabet[:-2]), remap(normalized, alphabet), remap(nonce, alphabet)]
    mixed = "".join(part[index] for index in range(max(map(len, parts)))
                    for part in parts if index < len(part))[:20]
    digest = hashlib.md5(mixed.encode("utf-8")).hexdigest()
    # Upstream mixes the first four characters and retains the final two in the sum.
    a, b, c, d = map(ord, digest[-6:-2])
    values = [mix_s(a) ^ mix_c(b) ^ mix_k(c) ^ mix_x(d),
              mix_x(a) ^ mix_s(b) ^ mix_c(c) ^ mix_k(d),
              mix_k(a) ^ mix_x(b) ^ mix_s(c) ^ mix_c(d),
              mix_c(a) ^ mix_k(b) ^ mix_x(c) ^ mix_s(d)]
    return remap(digest[:5], alphabet[:-4]) + f"{(sum(values) + sum(map(ord, digest[-2:]))) % 100:02d}"


def make_web_signature(path: str, version: str = "999.0.4", time_sec=None, nonce=None) -> dict:
    """Generate local Web signatures; App signatures continue using the hkey service."""
    time_sec = int(time.time()) if time_sec is None else int(time_sec)
    nonce = secrets.token_hex(16).upper() if nonce is None else str(nonce)
    return {"version": version, "hkey": make_web_hkey(path, time_sec + 1, nonce),
            "_time": str(time_sec), "nonce": nonce}
