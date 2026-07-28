"""Supported narration languages, default Edge-TTS voices, and caption fonts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

# language code → metadata used by API, prompts, TTS defaults, and captions.
SUPPORTED_LANGUAGES: dict[str, dict[str, Any]] = {
    "en": {
        "label": "English",
        "native_label": "English",
        "locale_prefix": "en",
        "default_voice": "en-US-ChristopherNeural",
        "script_name": "English",
        "font_candidates": [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        ],
    },
    "te": {
        "label": "Telugu",
        "native_label": "తెలుగు",
        "locale_prefix": "te",
        "default_voice": "te-IN-MohanNeural",
        "script_name": "Telugu (తెలుగు)",
        "font_candidates": [
            "/usr/share/fonts/truetype/noto/NotoSansTelugu-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansTelugu-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSerifTelugu-Bold.ttf",
        ],
    },
    "hi": {
        "label": "Hindi",
        "native_label": "हिन्दी",
        "locale_prefix": "hi",
        "default_voice": "hi-IN-MadhurNeural",
        "script_name": "Hindi (हिन्दी)",
        "font_candidates": [
            "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
        ],
    },
    "ta": {
        "label": "Tamil",
        "native_label": "தமிழ்",
        "locale_prefix": "ta",
        "default_voice": "ta-IN-ValluvarNeural",
        "script_name": "Tamil (தமிழ்)",
        "font_candidates": [
            "/usr/share/fonts/truetype/noto/NotoSansTamil-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansTamil-Regular.ttf",
        ],
    },
    "kn": {
        "label": "Kannada",
        "native_label": "ಕನ್ನಡ",
        "locale_prefix": "kn",
        "default_voice": "kn-IN-GaganNeural",
        "script_name": "Kannada (ಕನ್ನಡ)",
        "font_candidates": [
            "/usr/share/fonts/truetype/noto/NotoSansKannada-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansKannada-Regular.ttf",
        ],
    },
    "ml": {
        "label": "Malayalam",
        "native_label": "മലയാളം",
        "locale_prefix": "ml",
        "default_voice": "ml-IN-MidhunNeural",
        "script_name": "Malayalam (മലയാളം)",
        "font_candidates": [
            "/usr/share/fonts/truetype/noto/NotoSansMalayalam-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansMalayalam-Regular.ttf",
        ],
    },
    "bn": {
        "label": "Bengali",
        "native_label": "বাংলা",
        "locale_prefix": "bn",
        "default_voice": "bn-IN-BashkarNeural",
        "script_name": "Bengali (বাংলা)",
        "font_candidates": [
            "/usr/share/fonts/truetype/noto/NotoSansBengali-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf",
        ],
    },
    "gu": {
        "label": "Gujarati",
        "native_label": "ગુજરાતી",
        "locale_prefix": "gu",
        "default_voice": "gu-IN-NiranjanNeural",
        "script_name": "Gujarati (ગુજરાતી)",
        "font_candidates": [
            "/usr/share/fonts/truetype/noto/NotoSansGujarati-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansGujarati-Regular.ttf",
        ],
    },
    "mr": {
        "label": "Marathi",
        "native_label": "मराठी",
        "locale_prefix": "mr",
        "default_voice": "mr-IN-ManoharNeural",
        "script_name": "Marathi (मराठी)",
        "font_candidates": [
            "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
        ],
    },
    "es": {
        "label": "Spanish",
        "native_label": "Español",
        "locale_prefix": "es",
        "default_voice": "es-ES-AlvaroNeural",
        "script_name": "Spanish",
        "font_candidates": [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        ],
    },
    "fr": {
        "label": "French",
        "native_label": "Français",
        "locale_prefix": "fr",
        "default_voice": "fr-FR-HenriNeural",
        "script_name": "French",
        "font_candidates": [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        ],
    },
    "de": {
        "label": "German",
        "native_label": "Deutsch",
        "locale_prefix": "de",
        "default_voice": "de-DE-ConradNeural",
        "script_name": "German",
        "font_candidates": [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        ],
    },
}


def normalize_language(code: str | None) -> str:
    raw = (code or "en").strip().lower().replace("_", "-")
    if not raw:
        return "en"
    # Accept en-US → en, te-IN → te
    primary = raw.split("-", 1)[0]
    if primary in SUPPORTED_LANGUAGES:
        return primary
    if raw in SUPPORTED_LANGUAGES:
        return raw
    return "en"


def language_meta(code: str | None) -> dict[str, Any]:
    return SUPPORTED_LANGUAGES[normalize_language(code)]


def language_options() -> list[dict[str, str]]:
    return [
        {
            "id": code,
            "label": meta["label"],
            "native_label": meta["native_label"],
            "locale_prefix": meta["locale_prefix"],
            "default_voice": meta["default_voice"],
        }
        for code, meta in SUPPORTED_LANGUAGES.items()
    ]


def default_voice_for_language(code: str | None) -> str:
    return str(language_meta(code)["default_voice"])


def locale_prefix_for_language(code: str | None) -> str:
    return str(language_meta(code)["locale_prefix"])


def caption_font_for_language(code: str | None) -> str | None:
    for path in language_meta(code).get("font_candidates") or []:
        if Path(path).exists():
            return path
    return None


def script_language_name(code: str | None) -> str:
    return str(language_meta(code)["script_name"])
