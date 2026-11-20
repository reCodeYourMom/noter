"""Nettoyage des sorties Whisper : les phrases « fantômes » qu'il invente sur du silence.

Entraîné sur des sous-titres, Whisper remplit un passage muet ou inaudible avec les formules
de fin de vidéo qu'il a le plus vues : « ご視聴ありがとうございました », « Sous-titres réalisés par
la communauté d'Amara.org », « Thank you for watching »… Ces segments n'ont rien à faire dans
un transcript, et un transcript qui n'est fait que de ça signale un enregistrement sans parole.
"""
from __future__ import annotations

import re
import unicodedata

from noter.models import Segment

# Formules entières (comparées après normalisation : casse, ponctuation et espaces ignorées)
_PHRASES = (
    # japonais — de loin le plus fréquent sur un audio silencieux
    "ご視聴ありがとうございました",
    "ご視聴ありがとうございます",
    "ご清聴ありがとうございました",
    "チャンネル登録をお願いします",
    "チャンネル登録お願いします",
    "最後までご視聴いただきありがとうございました",
    # français
    "sous-titres réalisés par la communauté d'amara.org",
    "sous-titres réalisés para la communauté d'amara.org",
    "sous-titrage société radio-canada",
    "sous-titrage st' 501",
    "merci d'avoir regardé cette vidéo",
    "merci d'avoir regardé",
    "merci de votre attention",
    "abonnez-vous à la chaîne",
    "n'oubliez pas de vous abonner",
    # anglais
    "thank you for watching",
    "thanks for watching",
    "thank you for watching and see you next time",
    "please subscribe to my channel",
    "subtitles by the amara.org community",
    "subtitles by steamteamextra",
    # autres langues
    "untertitelung des zdf, 2020",
    "untertitel im auftrag des zdf",
    "untertitel von stephanie geiges",
    "sottotitoli creati dalla comunità amara.org",
    "subtítulos realizados por la comunidad de amara.org",
    "subtítulos por la comunidad de amara.org",
    "legendas pela comunidade amara.org",
    "字幕由amara.org社区提供",
    "字幕提供",
    "明镜与点点栏目",
    "시청해주셔서 감사합니다",
    "구독과 좋아요 부탁드립니다",
    "продолжение следует",
    "субтитры сделал dimatorzok",
    "редактор субтитров а.семкин корректор а.егорова",
)

# Fragments suffisants à eux seuls (génériques de sous-titrage, remerciements de fin de vidéo)
_FRAGMENTS = (
    "amara.org",
    "sous-titrage st'",
    "sous-titres réalisés par",
    "sous-titrage société",
    "untertitelung des zdf",
    "untertitel im auftrag des zdf",
    "ご視聴ありがとう",
    "ご清聴ありがとう",
    "チャンネル登録",
)

_PUNCT = re.compile(r"[\s\.,!?;:…。、！？「」『』()\[\]\"“”«»\-–—_~・]+")


def normalize(text: str) -> str:
    """Casse, accents composés, ponctuation et espaces neutralisés — garde apostrophes et lettres."""
    t = unicodedata.normalize("NFKC", text).casefold()
    return _PUNCT.sub("", t)


_PHRASES_N = frozenset(normalize(p) for p in _PHRASES)
_FRAGMENTS_N = tuple(normalize(f) for f in _FRAGMENTS)


def is_hallucination(text: str) -> bool:
    n = normalize(text)
    if not n:
        return True
    if n in _PHRASES_N:
        return True
    return any(f in n for f in _FRAGMENTS_N)


def clean_segments(segments: list[Segment]) -> tuple[list[Segment], int]:
    """Retire les segments fantômes. Retourne (segments gardés, nombre retiré)."""
    kept = [s for s in segments if not is_hallucination(s.text)]
    return kept, len(segments) - len(kept)
