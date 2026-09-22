"""Persistent rectangular HUD mask profiles and content-addressed HGM masks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
import struct
from pathlib import Path
import unicodedata
import uuid


MAGIC = 0x314D4748
VERSION = 1
HEADER = struct.Struct("<4I")
MIN_WIDTH = MIN_HEIGHT = 64
MAX_WIDTH = 7680
MAX_HEIGHT = 4320
MAX_RECTANGLES = 64
FEATHER_PIXELS = 4


def _normalized_title(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Target title must be a string")
    title = " ".join(unicodedata.normalize("NFKC", value).split()).casefold()
    if not title:
        raise ValueError("Target title must not be empty")
    return title


def _actual_int(value: object, name: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer")
    return value


def _target_identity(target: object) -> tuple[str, int, int]:
    if not isinstance(target, Mapping):
        raise ValueError("Target must be a mapping")
    try:
        title = _normalized_title(target["title"])
        width = _actual_int(target["width"], "Target width")
        height = _actual_int(target["height"], "Target height")
    except KeyError as exc:
        raise ValueError(f"Target is missing {exc.args[0]}") from exc
    if not MIN_WIDTH <= width <= MAX_WIDTH:
        raise ValueError(f"Target width must be between {MIN_WIDTH} and {MAX_WIDTH}")
    if not MIN_HEIGHT <= height <= MAX_HEIGHT:
        raise ValueError(f"Target height must be between {MIN_HEIGHT} and {MAX_HEIGHT}")
    return title, width, height


def _validated_rectangles(rectangles: object, width: int, height: int) -> list[list[int]]:
    if not isinstance(rectangles, list):
        raise ValueError("Rectangles must be a list")
    if len(rectangles) > MAX_RECTANGLES:
        raise ValueError(f"At most {MAX_RECTANGLES} rectangles are supported")
    result = []
    for index, rectangle in enumerate(rectangles):
        if not isinstance(rectangle, (list, tuple)) or len(rectangle) != 4:
            raise ValueError(f"Rectangle {index} must contain exactly four integers")
        if any(type(value) is not int for value in rectangle):
            raise ValueError(f"Rectangle {index} must contain exactly four integers")
        x0, y0, x1, y1 = rectangle
        if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
            raise ValueError(f"Rectangle {index} is outside the target geometry")
        if x1 - x0 < 2 or y1 - y0 < 2:
            raise ValueError(f"Rectangle {index} must be at least 2 by 2 pixels")
        result.append([x0, y0, x1, y1])
    return result


def _mask_directory(root: Path) -> Path:
    return Path(root) / "masks"


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def profile_key(target: object) -> str:
    """Return a stable key based only on normalized title and target geometry."""
    title, width, height = _target_identity(target)
    identity = json.dumps([title, width, height], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def load_profile(root: Path, target: object) -> dict | None:
    """Load and strictly validate a target's profile, or return None if absent."""
    title, width, height = _target_identity(target)
    path = _mask_directory(root) / f"{profile_key(target)}.json"
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Mask profile could not be read") from exc
    expected_fields = {"schema", "title", "width", "height", "rectangles"}
    if not isinstance(value, dict) or set(value) != expected_fields or value.get("schema") != 1:
        raise ValueError("Mask profile schema is invalid")
    if value.get("title") != title:
        raise ValueError("Mask profile title does not match the target")
    if type(value.get("width")) is not int or type(value.get("height")) is not int:
        raise ValueError("Mask profile geometry is invalid")
    if (value["width"], value["height"]) != (width, height):
        raise ValueError("Mask profile geometry does not match the target")
    value["rectangles"] = _validated_rectangles(value["rectangles"], width, height)
    return value


def save_profile(root: Path, target: object, rectangles: object) -> dict:
    """Validate and atomically save a rectangular profile for a target."""
    title, width, height = _target_identity(target)
    value = {
        "schema": 1,
        "title": title,
        "width": width,
        "height": height,
        "rectangles": _validated_rectangles(rectangles, width, height),
    }
    path = _mask_directory(root) / f"{profile_key(target)}.json"
    payload = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    _atomic_write(path, payload)
    return value


def _max_row(mask: bytearray, width: int, y: int, x0: int, x1: int, value: int) -> None:
    if x0 >= x1:
        return
    start = y * width + x0
    for offset in range(start, start + x1 - x0):
        if mask[offset] < value:
            mask[offset] = value


def _mask_pixels(width: int, height: int, rectangles: Sequence[Sequence[int]]) -> bytearray:
    mask = bytearray(width * height)
    # Each expansion ring is a four-pixel Chebyshev feather. Drawing by max
    # means a feather can never weaken another rectangle's core or feather.
    for x0, y0, x1, y1 in rectangles:
        for distance in range(FEATHER_PIXELS, 0, -1):
            value = 255 * (FEATHER_PIXELS + 1 - distance) // (FEATHER_PIXELS + 1)
            left = max(0, x0 - distance)
            right = min(width, x1 + distance)
            top = y0 - distance
            bottom = y1 + distance - 1
            if top >= 0:
                _max_row(mask, width, top, left, right, value)
            if bottom < height and bottom != top:
                _max_row(mask, width, bottom, left, right, value)
            side_top = max(0, top + 1)
            side_bottom = min(height, bottom)
            for y in range(side_top, side_bottom):
                if left < x0:
                    _max_row(mask, width, y, left, left + 1, value)
                if right > x1:
                    _max_row(mask, width, y, right - 1, right, value)
    for x0, y0, x1, y1 in rectangles:
        row = b"\xff" * (x1 - x0)
        for y in range(y0, y1):
            start = y * width + x0
            mask[start:start + len(row)] = row
    return mask


def build_mask(root: Path, target: object) -> Path:
    """Build or reuse an immutable, content-addressed HGM for a saved profile."""
    profile = load_profile(root, target)
    if profile is None:
        raise FileNotFoundError("No mask profile exists for this target")
    if not profile["rectangles"]:
        raise ValueError("A mask requires at least one rectangle")
    width, height = profile["width"], profile["height"]
    payload = HEADER.pack(MAGIC, VERSION, width, height) + bytes(
        _mask_pixels(width, height, profile["rectangles"])
    )
    digest = hashlib.sha256(payload).hexdigest()
    path = _mask_directory(root) / f"{digest}.hgm"
    if path.exists():
        validate_mask(path, width, height)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Existing content-addressed mask has invalid content")
        return path
    _atomic_write(path, payload)
    validate_mask(path, width, height)
    return path


def validate_mask(path: Path, width: int, height: int) -> None:
    """Validate an HGM header, exact geometry, and exact file size."""
    width = _actual_int(width, "Mask width")
    height = _actual_int(height, "Mask height")
    if not MIN_WIDTH <= width <= MAX_WIDTH or not MIN_HEIGHT <= height <= MAX_HEIGHT:
        raise ValueError("Mask geometry is outside the supported bounds")
    path = Path(path)
    try:
        size = path.stat().st_size
        with path.open("rb") as stream:
            header = stream.read(HEADER.size)
    except OSError as exc:
        raise ValueError("Mask could not be read") from exc
    if len(header) != HEADER.size:
        raise ValueError("Mask header is truncated")
    magic, version, actual_width, actual_height = HEADER.unpack(header)
    if magic != MAGIC or version != VERSION:
        raise ValueError("Mask magic or version is invalid")
    if (actual_width, actual_height) != (width, height):
        raise ValueError("Mask geometry does not match")
    if size != HEADER.size + width * height:
        raise ValueError("Mask file size is invalid")

