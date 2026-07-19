"""High-level asset acquisition service used by the orchestrator."""

from __future__ import annotations

from pathlib import Path

from config.settings import Settings, get_settings
from youtube_pipeline.assets.base import AssetProviderProtocol
from youtube_pipeline.assets.factory import build_asset_provider
from youtube_pipeline.exceptions import AssetAcquisitionError
from youtube_pipeline.models import MediaAsset, VideoScript
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)


class AssetService:
    """Acquire one visual asset per scene with graceful per-scene error isolation."""

    def __init__(
        self,
        settings: Settings | None = None,
        provider: AssetProviderProtocol | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.provider = provider or build_asset_provider(self.settings)

    def acquire_all(self, script: VideoScript, output_dir: Path) -> list[MediaAsset]:
        assets: list[MediaAsset] = []
        failures: list[str] = []

        for scene in script.scenes:
            try:
                asset = self.provider.fetch_for_scene(scene, output_dir)
                assets.append(asset)
                logger.info(
                    "Asset acquired | scene=%d | source=%s | path=%s",
                    scene.scene_id,
                    asset.source,
                    asset.path,
                )
            except Exception as exc:  # noqa: BLE001
                msg = f"scene {scene.scene_id}: {exc}"
                failures.append(msg)
                logger.error("Asset acquisition failed | %s", msg)

        if not assets:
            raise AssetAcquisitionError(
                "Failed to acquire any visual assets: " + "; ".join(failures)
            )
        if failures:
            logger.warning(
                "Partial asset acquisition (%d ok, %d failed)",
                len(assets),
                len(failures),
            )
        return assets
