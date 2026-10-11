from __future__ import annotations

from datetime import datetime

import numpy as np
import soundfile as sf
from tests.conftest import make_wav

from noter.audio.mixer import mix_wavs, wav_duration
from noter.models import (
    Recording,
    RecordingStatus,
    Segment,
    Source,
    Summary,
    format_duration,
    format_timestamp,
)
from noter.storage.files import recording_dir, slugify, summary_markdown, transcript_markdown


def test_mix_two_rates(tmp_path):
    mic = make_wav(tmp_path / "mic.wav", seconds=2.0, rate=48000, freq=440)
    sysw = make_wav(tmp_path / "sys.wav", seconds=1.0, rate=44100, freq=220)  # plus court, autre taux
    out = tmp_path / "out.wav"
    dur = mix_wavs(mic, sysw, out)
    assert abs(dur - 2.0) < 0.01
    data, rate = sf.read(str(out))
    assert rate == 48000 and data.ndim == 1 and np.max(np.abs(data)) <= 1.0
    # seconde moitié = micro seul (à 0.5 de gain)
    assert np.max(np.abs(data[rate + 1000 :])) < 0.2
    assert abs(wav_duration(out) - 2.0) < 0.01


def test_mix_mic_only(tmp_path):
    mic = make_wav(tmp_path / "mic.wav", seconds=1.5)
    out = tmp_path / "out.wav"
    assert abs(mix_wavs(mic, None, out) - 1.5) < 0.01
    assert sf.info(str(out)).channels == 1


def test_slugify_and_dir(tmp_path):
    assert slugify("Réunion Équipe : Q3 / budget !") == "Reunion-Equipe-Q3-budget"
    d1 = recording_dir(tmp_path, datetime(2026, 3, 3, 14, 30), "Sprint Planning")
    assert d1.name == "2026-03-03_14h30_Sprint-Planning" and d1.exists()
    d2 = recording_dir(tmp_path, datetime(2026, 3, 3, 14, 30), "Sprint Planning")
    assert d2.name == "2026-03-03_14h30_Sprint-Planning-2"


def test_markdown_renders(tmp_path):
    rec = Recording(id="abc", source=Source.MAC_MIC, status=RecordingStatus.DONE, started_at=datetime(2026, 1, 1, 9),
                    audio_path=tmp_path / "a.wav", dir_path=tmp_path, duration_s=3725, language="fr")
    segs = [Segment(0, 1, "Hello", speaker="A"), Segment(61, 62, "World")]
    t = transcript_markdown(rec, segs)
    assert "`00:00` **A** : Hello" in t and "`01:01` World" in t and "1h02" in t
    s = summary_markdown(rec, Summary(recording_id="abc", model="m", tldr="T", key_points=["k"]), segs)
    assert "## Points clés\n- k" in s and "<details>" in s
    assert format_duration(None) == "-" and format_duration(65) == "1:05" and format_timestamp(3661) == "1:01:01"
