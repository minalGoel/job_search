from __future__ import annotations

import json
import threading
from pathlib import Path

import structlog

_log = structlog.get_logger()

_MODEL_NAME = "all-MiniLM-L6-v2"
_PROFILE_PATH = Path(__file__).resolve().parent.parent / "data" / "candidate_profile.json"

_lock = threading.Lock()
_model = None
_candidate_embedding = None


def _load():
    """Lazy-load model + candidate embedding. Thread-safe singleton.

    Returns (model, embedding) or (None, None) if sentence-transformers
    is not installed — callers treat None as "unavailable, score = 0".
    """
    global _model, _candidate_embedding
    if _model is not None:
        return _model, _candidate_embedding
    with _lock:
        if _model is not None:
            return _model, _candidate_embedding
        try:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415
        except ImportError:
            _log.warning(
                "semantic_scorer.unavailable",
                reason="sentence-transformers not installed — run: pip install sentence-transformers",
            )
            return None, None

        _log.info("semantic_scorer.loading_model", model=_MODEL_NAME)
        try:
            _model = SentenceTransformer(_MODEL_NAME)
        except Exception as exc:
            _log.warning("semantic_scorer.load_failed", error=str(exc))
            return None, None

        candidate_text = _build_candidate_text()
        _candidate_embedding = _model.encode(candidate_text, convert_to_tensor=True)
        _log.info("semantic_scorer.ready", candidate_text_len=len(candidate_text))
        return _model, _candidate_embedding


def _build_candidate_text() -> str:
    """Build a rich text blob from the candidate profile JSON."""
    try:
        profile = json.loads(_PROFILE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return "Senior Product Manager B2B SaaS platform growth Delhi NCR 40 LPA"

    parts: list[str] = []
    if h := profile.get("headline"):
        parts.append(h)
    parts += profile.get("domain_strengths", [])
    parts += profile.get("industries_preferred", [])
    for p in profile.get("proof_points", []):
        if isinstance(p, dict) and p.get("text"):
            parts.append(p["text"])
    if wins := profile.get("notable_wins"):
        parts += wins
    return " | ".join(p for p in parts if p)


def score_semantic(job: dict) -> int:
    """Return 0-100 semantic similarity between this job and the candidate profile.

    Uses cosine similarity between sentence embeddings.
    Returns 0 gracefully when sentence-transformers is not installed or the
    job has no embeddable text.
    """
    model, candidate_emb = _load()
    if model is None or candidate_emb is None:
        return 0

    title = job.get("title", "") or ""
    description = (job.get("description", "") or "")[:600]
    job_text = f"{title}. {description}".strip().rstrip(".")
    if not job_text:
        return 0

    try:
        from sentence_transformers import util as st_util  # noqa: PLC0415

        job_emb = model.encode(job_text, convert_to_tensor=True)
        sim = float(st_util.cos_sim(candidate_emb, job_emb)[0][0])
        return max(0, min(100, int(sim * 100)))
    except Exception as exc:
        _log.warning("semantic_scorer.score_failed", error=str(exc))
        return 0
