# Task 2 Report: Models, tag normalization, and keyword fallback

**Status:** DONE  
**Date:** 2026-08-01

## Summary

Added the scene ambience/SFX data contract, deterministic normalization and keyword inference, fallback application, and soft-failing bundled pack path resolution.

## Deliverables

- `SfxCue` validates supported one-shot tags and clamps cue positions to `0.15–0.85`.
- `SceneData` now defaults to `ambience="none"` and `sfx=[]`, normalizes unknown ambience, drops invalid cues, and limits cues to two.
- `sfx_tags.py` normalizes tags, infers all supported ambience categories and one-shots from narration/visual text, and preserves explicit scene tags.
- `sfx_pack.py` resolves only known, existing ambience and one-shot MP3 files.
- `tests/test_sfx_tags.py` covers defaults, validation, clamping, limits, inference, fallback preservation, and pack resolution.

## Verification

```text
python -m pytest tests/test_models.py tests/test_sfx_tags.py -v
13 passed

python -c "... default pack resolution ..."
bundled pack paths resolved

python -m pytest
128 passed, 3 unrelated failures
```

The full-suite failures are outside this task: Gemini retry call count, missing local Telugu caption font, and `.env` overriding the expected default Edge TTS voice.
