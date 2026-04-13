"""
yc_startups/test_classifier.py — Smoke test for IndianNameClassifier.
"""
from __future__ import annotations

from yc_startups.name_classifier import classify, classify_batch

INDIAN_NAMES = [
    "Rajesh Sharma", "Priya Patel", "Suresh Kumar", "Anita Desai",
    "Mohammed Iyer", "Gurpreet Singh", "Venkatesh Rao", "Fatima Shaikh",
    "Ravi", "Lakshmi Pillai", "John D'Souza", "Arjun Mehta",
]

NON_INDIAN_NAMES = [
    "John Smith", "Emma Johnson", "Li Wei", "Yuki Tanaka",
    "Carlos Garcia", "Anna Mueller", "Mohammed Al-Rashid", "James Brown",
    "Sophie Martin", "Wang Fang", "David Williams", "Maria Santos",
]

AMBIGUOUS_NAMES = [
    "John Singh", "Priya Williams", "Michael Kumar", "Sarah Nair", "Ahmed Khan",
]


def main() -> None:
    print("=" * 70)
    print("INDIAN NAMES (expect is_indian=True)")
    print("=" * 70)
    indian_correct = 0
    for name in INDIAN_NAMES:
        result = classify(name)
        status = "PASS" if result["is_indian"] else "FAIL"
        if result["is_indian"]:
            indian_correct += 1
        print(f"  [{status}] {result}")

    print(f"\n  Accuracy: {indian_correct}/{len(INDIAN_NAMES)}")

    print("\n" + "=" * 70)
    print("NON-INDIAN NAMES (expect is_indian=False)")
    print("=" * 70)
    non_indian_correct = 0
    for name in NON_INDIAN_NAMES:
        result = classify(name)
        status = "PASS" if not result["is_indian"] else "FAIL"
        if not result["is_indian"]:
            non_indian_correct += 1
        print(f"  [{status}] {result}")

    print(f"\n  Accuracy: {non_indian_correct}/{len(NON_INDIAN_NAMES)}")

    print("\n" + "=" * 70)
    print("AMBIGUOUS / EDGE CASES (just showing scores)")
    print("=" * 70)
    for name in AMBIGUOUS_NAMES:
        result = classify(name)
        print(f"  {result}")

    print("\n" + "=" * 70)
    print("BATCH CLASSIFICATION TEST")
    print("=" * 70)
    all_names = INDIAN_NAMES + NON_INDIAN_NAMES + AMBIGUOUS_NAMES
    batch_results = classify_batch(all_names)
    for r in batch_results:
        print(f"  {r['name']:25s} → indian={r['is_indian']!s:5s}  conf={r['confidence']:.3f}  matched={r['matched_on']}")

    print(f"\nTotal: {indian_correct + non_indian_correct}/{len(INDIAN_NAMES) + len(NON_INDIAN_NAMES)} correct on labeled names")


if __name__ == "__main__":
    main()
