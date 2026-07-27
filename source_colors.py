from __future__ import annotations

import colorsys


SourceId = tuple[int, int]

_SOURCE_PALETTE = (
    "#0072B2",
    "#D55E00",
    "#E69F00",
    "#009E73",
    "#8E5EA2",
    "#CC79A7",
    "#6A3D9A",
    "#00A6A6",
    "#C2185B",
    "#8B6914",
    "#E15759",
    "#4E79A7",
    "#F28E2B",
    "#59A14F",
    "#4C9F38",
    "#76B7B2",
    "#EDC948",
    "#7A5195",
    "#FF7C7C",
    "#9C755F",
    "#B22222",
    "#17A8B8",
    "#577A2D",
    "#A05195",
)
_LIGHTNESS_VARIANTS = (0.0, -0.10, 0.10, -0.17, 0.17, -0.05, 0.05)


def _source_index(track: int, channel: int) -> int:
    if track < 0:
        return 512 + channel
    diagonal = track + channel
    return diagonal * (diagonal + 1) // 2 + channel


def _palette_variant(color: str, cycle: int) -> str:
    if cycle <= 0:
        return color
    red = int(color[1:3], 16) / 255
    green = int(color[3:5], 16) / 255
    blue = int(color[5:7], 16) / 255
    hue, lightness, saturation = colorsys.rgb_to_hls(red, green, blue)
    lightness += _LIGHTNESS_VARIANTS[cycle % len(_LIGHTNESS_VARIANTS)]
    lightness = max(0.28, min(0.68, lightness))
    saturation = max(0.52, min(0.88, saturation - 0.035 * (cycle // 7)))
    red, green, blue = colorsys.hls_to_rgb(hue, lightness, saturation)
    return "#{:02X}{:02X}{:02X}".format(
        round(red * 255),
        round(green * 255),
        round(blue * 255),
    )


def _encode_source_identity(color: str, source_index: int) -> str:
    red = int(color[1:3], 16)
    green = int(color[3:5], 16)
    blue = int(color[5:7], 16)
    identity = source_index % 64
    red = (red & 0xFC) | (identity & 0x03)
    green = (green & 0xFC) | ((identity >> 2) & 0x03)
    blue = (blue & 0xFC) | ((identity >> 4) & 0x03)
    return f"#{red:02X}{green:02X}{blue:02X}"


def track_channel_color(track: int, channel: int) -> str:
    """Return a stable, high-contrast color for one MIDI track/channel pair."""
    normalized_track = max(-1, int(track))
    normalized_channel = max(0, min(15, int(channel)))
    source_index = _source_index(normalized_track, normalized_channel)
    palette_index = source_index % len(_SOURCE_PALETTE)
    return _encode_source_identity(
        _palette_variant(
            _SOURCE_PALETTE[palette_index],
            source_index // len(_SOURCE_PALETTE),
        ),
        source_index,
    )


def contrasting_text_color(background: str) -> str:
    """Return readable text for a source-colored TC circle."""
    red = int(background[1:3], 16) / 255
    green = int(background[3:5], 16) / 255
    blue = int(background[5:7], 16) / 255

    def linearize(component: float) -> float:
        if component <= 0.04045:
            return component / 12.92
        return ((component + 0.055) / 1.055) ** 2.4

    luminance = (
        0.2126 * linearize(red)
        + 0.7152 * linearize(green)
        + 0.0722 * linearize(blue)
    )
    return "#101820" if luminance > 0.42 else "#FFFFFF"
