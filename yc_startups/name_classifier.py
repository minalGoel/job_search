"""
yc_startups/name_classifier.py — Offline Indian name classifier using char n-gram models.

Two models: first_name_model (trained on first names) and last_name_model (trained on last names).
A name is classified as Indian if EITHER the first or last name scores above threshold.

Auto-initializes on import: loads from cache or trains from scratch.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

# Dual-threshold: require high confidence from a single model, OR moderate
# confidence from BOTH models agreeing.  This eliminates false positives
# where only the last-name model fires on a non-Indian surname.
THRESHOLD_SINGLE = 0.88   # one model alone must be very confident
THRESHOLD_BOTH   = 0.65   # lower bar when both models agree

DATA_DIR = Path(__file__).parent / "data"
MODELS_DIR = Path(__file__).parent / "models"

FIRST_MODEL_PATH = MODELS_DIR / "first_name_model.joblib"
LAST_MODEL_PATH = MODELS_DIR / "last_name_model.joblib"


def _load_names(filepath: Path) -> list[str]:
    """Load names from a text file, one per line."""
    if not filepath.exists():
        return []
    return [line.strip() for line in filepath.read_text(encoding="utf-8").splitlines() if line.strip()]


def _train_model(indian_path: Path, non_indian_path: Path, model_name: str) -> Pipeline:
    """Train a single TF-IDF + LogisticRegression model."""
    indian_names = _load_names(indian_path)
    non_indian_names = _load_names(non_indian_path)

    if not indian_names or not non_indian_names:
        raise RuntimeError(
            f"Training data missing for {model_name}. "
            f"Indian: {len(indian_names)}, Non-Indian: {len(non_indian_names)}"
        )

    X = indian_names + non_indian_names
    y = [1] * len(indian_names) + [0] * len(non_indian_names)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42
    )

    pipeline = Pipeline([
        ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=1)),
        ("clf", LogisticRegression(C=5, max_iter=1000, random_state=42)),
    ])

    pipeline.fit(X_train, y_train)

    # Print evaluation
    y_pred = pipeline.predict(X_test)
    print(f"\n=== {model_name} Classification Report ===")
    print(classification_report(y_test, y_pred, target_names=["Non-Indian", "Indian"]))

    # Sample predictions
    sample_idx = np.random.RandomState(42).choice(len(X_test), min(5, len(X_test)), replace=False)
    print(f"Sample predictions ({model_name}):")
    for i in sample_idx:
        prob = pipeline.predict_proba([X_test[i]])[0][1]
        print(f"  {X_test[i]:20s} → P(Indian)={prob:.3f}  actual={y_test[i]}")

    return pipeline


def train_and_save() -> tuple[Pipeline, Pipeline]:
    """Train both models and save to disk."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    print("Training first name model...")
    first_model = _train_model(
        DATA_DIR / "indian_firstnames.txt",
        DATA_DIR / "non_indian_firstnames.txt",
        "first_name_model",
    )
    joblib.dump(first_model, FIRST_MODEL_PATH)
    print(f"Saved: {FIRST_MODEL_PATH}")

    print("\nTraining last name model...")
    last_model = _train_model(
        DATA_DIR / "indian_lastnames.txt",
        DATA_DIR / "non_indian_lastnames.txt",
        "last_name_model",
    )
    joblib.dump(last_model, LAST_MODEL_PATH)
    print(f"Saved: {LAST_MODEL_PATH}")

    return first_model, last_model


def _ensure_training_data() -> None:
    """Run build_training_data.py if data files are missing."""
    required = [
        DATA_DIR / "indian_firstnames.txt",
        DATA_DIR / "indian_lastnames.txt",
        DATA_DIR / "non_indian_firstnames.txt",
        DATA_DIR / "non_indian_lastnames.txt",
    ]
    if all(f.exists() and f.stat().st_size > 0 for f in required):
        return

    print("Training data not found. Fetching...")
    build_script = Path(__file__).parent / "build_training_data.py"
    subprocess.run([sys.executable, str(build_script)], check=True)


def _init_models() -> tuple[Pipeline, Pipeline]:
    """Load models from cache or train from scratch."""
    if FIRST_MODEL_PATH.exists() and LAST_MODEL_PATH.exists():
        first_model = joblib.load(FIRST_MODEL_PATH)
        last_model = joblib.load(LAST_MODEL_PATH)
        print("Name classifier loaded from cache")
        return first_model, last_model

    _ensure_training_data()
    return train_and_save()


# Module-level initialization
_first_model, _last_model = _init_models()


def _is_indian(first_score: float, last_score: float) -> tuple[bool, str]:
    """Apply dual-threshold logic to determine Indian classification.

    Returns (is_indian, matched_on) tuple.
    """
    both_moderate = first_score >= THRESHOLD_BOTH and last_score >= THRESHOLD_BOTH
    first_strong = first_score >= THRESHOLD_SINGLE
    last_strong = last_score >= THRESHOLD_SINGLE

    if both_moderate:
        matched_on = "both"
        is_indian = True
    elif first_strong:
        matched_on = "first"
        is_indian = True
    elif last_strong:
        matched_on = "last"
        is_indian = True
    else:
        matched_on = "neither"
        is_indian = False

    return is_indian, matched_on


def classify(full_name: str) -> dict:
    """Classify a single name as Indian or non-Indian.

    Uses dual-threshold: requires EITHER very high confidence from one model
    (>= THRESHOLD_SINGLE) OR moderate confidence from BOTH models agreeing
    (>= THRESHOLD_BOTH).  This eliminates false positives where only the
    last-name n-gram model fires on a non-Indian surname.

    Returns:
        Dict with keys: name, is_indian, confidence, first_name_score,
        last_name_score, matched_on.
    """
    tokens = full_name.strip().split()
    if not tokens:
        return {
            "name": full_name,
            "is_indian": False,
            "confidence": 0.0,
            "first_name_score": 0.0,
            "last_name_score": 0.0,
            "matched_on": "neither",
        }

    # For hyphenated first names (e.g. "Jan-Hendrik"), use only the part before
    # the hyphen — the full hyphenated string contains n-grams from both parts
    # and produces unreliable scores.
    first_token = tokens[0].lower().split("-")[0]

    if len(tokens) == 1:
        # Single token — run both models on the same (de-hyphenated) token
        first_score = float(_first_model.predict_proba([first_token])[0][1])
        last_score = float(_last_model.predict_proba([first_token])[0][1])
    elif len(tokens) == 2:
        first_score = float(_first_model.predict_proba([first_token])[0][1])
        last_score = float(_last_model.predict_proba([tokens[1].lower()])[0][1])
    else:
        # 3+ tokens: first = first name, last = last name, middle ignored
        first_score = float(_first_model.predict_proba([first_token])[0][1])
        last_score = float(_last_model.predict_proba([tokens[-1].lower()])[0][1])

    is_indian, matched_on = _is_indian(first_score, last_score)

    return {
        "name": full_name,
        "is_indian": is_indian,
        "confidence": round(max(first_score, last_score), 3),
        "first_name_score": round(first_score, 3),
        "last_name_score": round(last_score, 3),
        "matched_on": matched_on,
    }


def classify_batch(names: list[str]) -> list[dict]:
    """Classify a batch of names using vectorized prediction.

    Args:
        names: List of full name strings.

    Returns:
        List of classification result dicts (same format as classify()).
    """
    if not names:
        return []

    # Split all names into first and last tokens
    first_tokens = []
    last_tokens = []
    token_lists = []

    for name in names:
        tokens = name.strip().split()
        token_lists.append(tokens)
        if not tokens:
            first_tokens.append("")
            last_tokens.append("")
        elif len(tokens) == 1:
            # De-hyphenate: "Jan-Hendrik" → "Jan"
            ft = tokens[0].lower().split("-")[0]
            first_tokens.append(ft)
            last_tokens.append(ft)
        else:
            first_tokens.append(tokens[0].lower().split("-")[0])
            last_tokens.append(tokens[-1].lower())

    # Vectorized prediction
    first_scores = np.zeros(len(names))
    last_scores = np.zeros(len(names))

    # Filter out empty strings for prediction
    non_empty_first = [(i, t) for i, t in enumerate(first_tokens) if t]
    non_empty_last = [(i, t) for i, t in enumerate(last_tokens) if t]

    if non_empty_first:
        indices, tokens = zip(*non_empty_first)
        probs = _first_model.predict_proba(list(tokens))[:, 1]
        for idx, prob in zip(indices, probs):
            first_scores[idx] = prob

    if non_empty_last:
        indices, tokens = zip(*non_empty_last)
        probs = _last_model.predict_proba(list(tokens))[:, 1]
        for idx, prob in zip(indices, probs):
            last_scores[idx] = prob

    # Build results using dual-threshold logic
    results = []
    for i, name in enumerate(names):
        fs = float(first_scores[i])
        ls = float(last_scores[i])
        is_indian, matched_on = _is_indian(fs, ls)

        results.append({
            "name": name,
            "is_indian": is_indian,
            "confidence": round(max(fs, ls), 3),
            "first_name_score": round(fs, 3),
            "last_name_score": round(ls, 3),
            "matched_on": matched_on,
        })

    return results


def classify_nationality(name: str) -> dict:
    """Drop-in replacement mimicking nationalize.io response format.

    Returns:
        Dict matching nationalize.io shape:
        {"name": ..., "country": [{"country_id": "IN", "probability": ...}]}
    """
    result = classify(name)
    if result["is_indian"]:
        return {
            "name": name,
            "country": [{"country_id": "IN", "probability": result["confidence"]}],
        }
    return {"name": name, "country": []}
