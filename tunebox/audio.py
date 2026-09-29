"""Volume curve and equaliser: the numbers mpv gets."""
from .config import EQ_FREQS, EQ_PRESETS, NORMALIZE_FILTER, VOL_RANGE_DB
from .settings import settings


def level_to_mpv(level: float, extra_db: float = 0.0) -> float:
    """Slider level (0-100) to mpv volume. The slider is linear in dB; mpv cubes its
    volume (gain = (v/100)^3), so v = 100 * gain^(1/3) = 100 * 10^(dB/60)."""
    if level <= 0:
        return 0
    db = (level - 100) * VOL_RANGE_DB / 100 + extra_db
    return round(100 * 10 ** (db / 60), 2)


def eq_bands() -> list[float]:
    eq = settings["eq"]
    return eq["custom"] if eq["preset"] == "custom" else EQ_PRESETS.get(eq["preset"], EQ_PRESETS["flat"])


def pre_cut(bands) -> str:
    """Linear gain for the pre-cut that keeps EQ boosts from clipping."""
    return f"{10 ** (-max(0, max(bands)) / 20):.5f}"


def eq_filter(bands=None) -> str:
    """mpv audio filter string: a fixed chain of named filters (optional loudness normaliser,
    pre-cut, one equalizer per band). Its gains can then be changed live with af-command, without
    rebuilding the chain, which would briefly interrupt playback.
    The normaliser comes first: it looks seconds ahead, so anything before it is only heard that
    much later. After it, an EQ change is heard at once."""
    bands = list(bands if bands is not None else eq_bands())
    parts = [NORMALIZE_FILTER] if settings.get("normalize") else []
    parts.append(f"volume@pre=volume={pre_cut(bands)}")
    parts += [f"equalizer@b{i}=f={f}:t=o:w=1:g={g}" for i, (f, g) in enumerate(zip(EQ_FREQS, bands))]
    return "@tbeq:lavfi=[" + ",".join(parts) + "]"
