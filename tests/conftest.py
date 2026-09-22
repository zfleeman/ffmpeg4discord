"""Fixtures shared by more than one test file. pytest passes a fixture to any test that names it as an argument."""

import pytest


@pytest.fixture
def probe(monkeypatch):
    """Fake `ffmpeg.probe` output for a 2-minute 1080p30 clip with one audio track. Edit it before building a TwoPass."""
    data = {
        "program_version": {"version": "9.0.1", "configuration": ""},
        "format": {"duration": "120.0", "size": "53000000"},
        "streams": [
            {"codec_type": "video", "width": 1920, "height": 1080, "r_frame_rate": "30/1", "index": 0},
            {"codec_type": "audio", "bit_rate": "128000", "index": 1},
        ],
    }
    monkeypatch.setattr("ffmpeg4discord.twopass.ffmpeg.probe", lambda *args, **kwargs: data)
    return data
