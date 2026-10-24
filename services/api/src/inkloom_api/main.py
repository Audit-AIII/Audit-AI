from __future__ import annotations

import logging

from dotenv import load_dotenv

# Must run before anything reads os.environ directly - our own Settings (config.py) parses
# .env on its own via pydantic-settings, but that never touches the real process environment.
# inkloom_verify.providers.openrouter.OpenRouterSettings.from_env() reads os.environ directly,
# so OPENROUTER_API_KEY / INKLOOM_LLM_MODELS in .env would otherwise never reach it.
load_dotenv()

from fastapi import Depends, FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from .body_limit import BodySizeLimitMiddleware  # noqa: E402
from .config import get_settings  # noqa: E402
from .db import get_db  # noqa: E402
from .errors import install_error_handlers  # noqa: E402
from .logging import RequestIdMiddleware, configure_logging  # noqa: E402
<<<<<<< HEAD
from .routers import analytics, auth, brands, content, content_versions, evaluations, reviews  # noqa: E402
=======
from .routers import auth, brands, content, content_versions, evaluations, reviews  # noqa: E402
>>>>>>> 6b23c112bb2360f3710bc25c6629254199b169ad

settings = get_settings()
configure_logging(settings.log_level)
# Refuses to start in production with an unsafe configuration; elsewhere, says what is unsafe
# (setting names only, never values).
for _problem in settings.check_startup():
    logging.getLogger("inkloom_api.config").warning("insecure configuration: %s", _problem)

app = FastAPI(title="INKLOOM AI backend", version="0.1.0")
# Innermost: the body limit runs before any route reads or parses a body.
app.add_middleware(
    BodySizeLimitMiddleware,
    max_json_bytes=settings.max_request_body_bytes,
    max_upload_bytes=settings.max_source_upload_bytes + 1_000_000,
)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
install_error_handlers(app)
app.include_router(auth.router)
app.include_router(brands.router)
app.include_router(reviews.router)
app.include_router(content.router)
app.include_router(content_versions.router)
<<<<<<< HEAD
app.include_router(analytics.router)
=======
>>>>>>> 6b23c112bb2360f3710bc25c6629254199b169ad
app.include_router(evaluations.router)


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
