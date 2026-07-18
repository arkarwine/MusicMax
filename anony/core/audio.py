"""Central audio-mode definitions and FFmpeg filter construction."""

AUDIO_MODES = ("original", "spatial", "hall")

_FILTERS = {
    "spatial": (
        "aformat=channel_layouts=stereo,"
        "stereowiden=delay=12:feedback=0.12:crossfeed=0.08:drymix=0.92,"
        "volume=0.96,alimiter=limit=0.95"
    ),
    "hall": (
        "aformat=channel_layouts=stereo,"
        "stereowiden=delay=18:feedback=0.20:crossfeed=0.10:drymix=0.88,"
        "aecho=0.72:0.88:45|95|160:0.24|0.16|0.10,"
        "volume=0.86,alimiter=limit=0.95"
    ),
}


def normalize_audio_mode(mode: str | None) -> str:
    return mode if mode in AUDIO_MODES else "original"


def next_audio_mode(mode: str | None) -> str:
    current = normalize_audio_mode(mode)
    return AUDIO_MODES[(AUDIO_MODES.index(current) + 1) % len(AUDIO_MODES)]


def audio_filter(mode: str | None) -> str | None:
    return _FILTERS.get(normalize_audio_mode(mode))


def build_ffmpeg_parameters(seek_time: int, mode: str | None) -> str | None:
    parameters = []
    if seek_time > 1:
        parameters.append(f"-ss {seek_time}")
    selected_filter = audio_filter(mode)
    if selected_filter:
        parameters.append(f'---mid -af "{selected_filter}"')
    return " ".join(parameters) or None
