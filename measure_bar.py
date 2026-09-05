#!/usr/bin/env python3
"""Measure the Organic/Boosted (or any two-tone) split of a funnel bar by pixel color, instead of relying on the vision model's visual estimate.
Usage: python3 measure_bar.py <screenshot.png>
"""
import sys
from PIL import Image

def is_blueish(c):
    r, g, b = c
    return b > 120 and b > r + 20 and b > g

def main(path):
    img = Image.open(path).convert('RGB')
    w, h = img.size
    px = img.load()

    bar_rows = []
    for y in range(h):
        count = sum(1 for x in range(w) if is_blueish(px[x, y]))
        if count > w * 0.15:
            bar_rows.append(y)
    if not bar_rows:
        print("No bar found"); return

    # first contiguous band = the base/top bar
    band = [bar_rows[0]]
    for y in bar_rows[1:]:
        if y - band[-1] <= 2:
            band.append(y)
        else:
            break
    y = band[len(band) // 2]

    row = [px[x, y] for x in range(w)]
    bar_xs = [x for x, c in enumerate(row) if is_blueish(c)]
    x0, x1 = min(bar_xs), max(bar_xs)

    # find the color transition inside the bar (largest single color jump)
    colors = [row[x] for x in range(x0, x1 + 1)]
    best_split, best_jump = x0, 0
    for i in range(1, len(colors)):
        jump = sum(abs(a - b) for a, b in zip(colors[i], colors[i - 1]))
        if jump > best_jump:
            best_jump, best_split = jump, x0 + i

    total = x1 - x0
    left_pct = (best_split - x0) / total * 100
    right_pct = 100 - left_pct
    print(f"bar spans x={x0}-{x1} ({total}px), split at x={best_split}")
    print(f"left segment: {left_pct:.1f}%  |  right segment: {right_pct:.1f}%")

if __name__ == '__main__':
    main(sys.argv[1])
