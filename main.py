#!/usr/bin/env python3
"""Deterministic pump.fun top-five forecast.

The hello stream is read as one batch of historical orders at each slot.  It
uses only local history, so no network, randomness, or wall-clock state can
affect a forecast.
"""

import json
import math
import os
from datetime import datetime, timedelta

INPUT_DIR = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
OUTPUT_DIR = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
NAMED_MASS = 0.65
CANDIDATES = 12
TEMPERATURE = 0.22
RANK_PENALTY = 0.35
MICRO = 1_000_000


def instant(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def clamp(value, low, high):
    return max(low, min(high, value))


def log_cap(lamports):
    return math.log10(int(lamports)) - 9.0


def normal_above(value, mean, deviation):
    if value == -math.inf:
        return 1.0
    if value == math.inf:
        return 0.0
    return 0.5 * math.erfc((value - mean) / (deviation * math.sqrt(2.0)))


def down(value):
    return math.floor(max(0.0, value) * MICRO) / MICRO


def mark_rows(history_path):
    marks = []
    with open(history_path, encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            mark = json.loads(line)
            if mark.get("ok") and isinstance(mark.get("rows"), list):
                marks.append(mark)
    marks.sort(key=lambda mark: (mark.get("at", ""), str(mark.get("slot", ""))))
    return marks


def rank_of(row):
    try:
        return int(row.get("rank"))
    except (TypeError, ValueError):
        return 10**9


def mint_key(row):
    mint = row.get("mint")
    return mint if isinstance(mint, str) else ""


def cap_at_or_before(points, cutoff):
    result = None
    for observed, cap in points:
        if observed > cutoff:
            break
        result = cap
    return result


def main():
    with open(os.path.join(INPUT_DIR, "task.json"), encoding="utf-8") as source:
        task = json.load(source)
    marks = mark_rows(os.path.join(INPUT_DIR, "history.ndjson"))
    if not marks:
        raise SystemExit("history has no successful marks")

    places = int(task["places"])
    edges = [float(edge) for edge in task["size"]["edges"]]
    last = marks[-1]
    last_time = instant(last["at"])

    history = {}
    for mark in marks:
        observed = instant(mark["at"])
        for row in mark["rows"]:
            mint = row.get("mint")
            try:
                cap = int(row.get("market_cap_lamports"))
            except (TypeError, ValueError):
                continue
            if isinstance(mint, str) and mint and cap > 0:
                history.setdefault(mint, []).append((observed, cap))
    for points in history.values():
        points.sort()

    current_rows = sorted(last["rows"], key=lambda row: (rank_of(row), mint_key(row)))
    seen = set()
    coins = []
    for row in current_rows:
        mint = row.get("mint")
        if not isinstance(mint, str) or mint in seen or mint not in history:
            continue
        try:
            current = int(row.get("market_cap_lamports"))
        except (TypeError, ValueError):
            continue
        if current <= 0:
            continue
        seen.add(mint)
        points = history[mint]
        cap30 = cap_at_or_before(points, last_time - timedelta(minutes=30))
        cap60 = cap_at_or_before(points, last_time - timedelta(hours=1))
        growth30 = math.log10(current / cap30) if cap30 else 0.0
        growth60 = math.log10(current / cap60) if cap60 else 0.0
        momentum = (clamp(growth30, -1.0, 1.0) + clamp(growth60, -1.0, 1.0)) / 2.0
        graduated = row.get("venue") == "pool" and bool(row.get("complete"))
        size = log_cap(current)
        coins.append({
            "mint": mint,
            "score": size + 0.7 * momentum + 0.12 * float(graduated),
            "size": size + 0.5 * clamp(growth60, -1.0, 1.0),
        })

    if len(coins) < places:
        raise SystemExit("fewer usable current coins than requested places")
    coins.sort(key=lambda coin: (-coin["score"], coin["mint"]))
    for ordinal, coin in enumerate(coins, 1):
        coin["rank"] = ordinal

    reads = task.get("reads", [])
    horizon = 0.0
    if reads:
        horizon = max(0.0, (instant(reads[0]) - last_time).total_seconds() / 3600.0)
    deviation = min(0.65, 0.35 + 0.03 * horizon)

    probabilities = []
    shortlist = coins[:CANDIDATES]
    for place in range(1, places + 1):
        shifted = [coin["score"] - RANK_PENALTY * abs(coin["rank"] - place) for coin in shortlist]
        peak = max(shifted)
        weights = [math.exp((value - peak) / TEMPERATURE) for value in shifted]
        total = sum(weights)
        for coin, weight in zip(shortlist, weights):
            probability = down(NAMED_MASS * weight / total)
            if probability:
                probabilities.append({"mint": coin["mint"], "place": place, "p": probability})

    sizes = []
    for place, coin in enumerate(coins[:places], 1):
        for bin_number in range(len(edges) + 1):
            low = -math.inf if bin_number == 0 else edges[bin_number - 1]
            high = math.inf if bin_number == len(edges) else edges[bin_number]
            probability = down(normal_above(low, coin["size"], deviation)
                               - normal_above(high, coin["size"], deviation))
            if probability:
                sizes.append({"place": place, "bin": bin_number, "p": probability})

    forecast = {
        "probabilities": probabilities,
        "top5": [coin["mint"] for coin in coins[:places]],
        "sizes": sizes,
    }
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, task.get("output", "forecast.json"))
    with open(path, "w", encoding="utf-8") as target:
        target.write(json.dumps(forecast, separators=(",", ":")))
        target.write(chr(10))


if __name__ == "__main__":
    main()
