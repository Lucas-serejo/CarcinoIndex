"""FastAPI application factory and SAM 2 process lifecycle."""

from __future__ import annotations

from contextlib import asynccontextmanager
import os
from typing import AsyncIterator

from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from backend.ai.segmentation import SAM2Segmenter
from backend.app.api import api_router, health_router
from backend.app.api.errors import install_error_handlers
from backend.app.core.config import Settings
from backend.app.services.segmentation_service import SegmentationService
from backend.app.persistence.database import (
    PersistenceSettings, create_database_engine, create_session_factory,
)
from backend.app.storage.local import LocalStorage


def create_app(
    *,
    settings: Settings | None = None,
    segmentation_service: SegmentationService | None = None,
    session_factory: sessionmaker[Session] | None = None,
    storage: LocalStorage | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    if (session_factory is None) != (storage is None):
        raise ValueError("Provide session_factory and storage together.")

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.settings = resolved_settings
        owned_service: SegmentationService | None = None
        if segmentation_service is not None:
            application.state.segmentation_service = segmentation_service
        else:
            checkpoint = resolved_settings.sam2_checkpoint_path
            if checkpoint is None:
                raise RuntimeError(
                    "SAM2_CHECKPOINT_PATH is required to start the segmentation API."
                )
            segmenter = SAM2Segmenter(
                checkpoint_path=checkpoint,
                model_config=resolved_settings.sam2_model_config,
                device=resolved_settings.sam2_device,
                dtype=resolved_settings.sam2_dtype,
            )
            try:
                segmenter.load()
            except Exception:
                segmenter.close()
                raise
            owned_service = SegmentationService(segmenter)
            application.state.segmentation_service = owned_service

        engine = None
        try:
            application.state.session_factory = session_factory
            application.state.storage = storage
            if session_factory is None and os.environ.get("DATABASE_URL", "").strip():
                persistence = PersistenceSettings.from_env()
                engine = create_database_engine(persistence)
                application.state.session_factory = create_session_factory(engine)
                application.state.storage = LocalStorage(persistence.storage_root)
            yield
        finally:
            if engine is not None:
                engine.dispose()
            application.state.session_factory = None
            application.state.storage = None
            if owned_service is not None:
                owned_service.close()
            application.state.segmentation_service = None

    application = FastAPI(
        title="CarcinoIndex API",
        description=(
            "Experimental API for assisted SAM 2 segmentation and manual PCI "
            "composition. It is not intended for autonomous diagnosis."
        ),
        version="0.3.0",
        lifespan=lifespan,
    )
    application.include_router(health_router)
    application.include_router(api_router, prefix=resolved_settings.api_prefix)
    install_error_handlers(application)
    return application


app = create_app()
