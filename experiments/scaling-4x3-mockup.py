#!/usr/bin/env python3
"""mockup_4x3.py OUT: a SYNTHETIC target shape for the 4x3 scaling figure, drawn from the model below, NOT from any run. The owner asked (2026-11-08 09:00) to see
what a good figure would look like before the remaining runs finish. Every curve is a formula; the only things taken from the real experiment are the panel layout, the
windows (ZooKeeper 30 min, the others 45) and the order of magnitude of each system's path counts (each panel's top stays under the table's maximum path of its
system). The output says MOCK-UP on its face and in its file name; it must never replace output/scaling-12.* or experiments/scaling-4x3.*.

The model: a panel of kind "fast" reaches its fixed point P: c_k(t) = P (1 - exp(-(t / tau_k)^2)), tau_k = 0.6 window / k^0.6, so every machine count meets at P, more
machines sooner. A panel of kind "branches" does not converge inside the window: c_k(t) = A_k t / (t + h), A_k = A_1 k^0.55, h = window: strictly layered 1 < 2 <
4 < 8, with the gain from 4 to 8 smaller than from 2 to 4. Lines are smoothed as the real figure's are (Gaussian, 5 % of the window)."""
import sys

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

K = (1, 2, 4, 8)
COLORS = {1: "#9ecae1", 2: "#4292c6", 3: "#2171b5", 4: "#1f5f9e", 8: "#0b2a4a"}
# system, panel label, kind, window (min), level: P for fast (meets), A_1 for branches (1 machine's level at the window)
PANELS = [
    ("HDFS", ["adhoc-52", "adhoc-50", "adhoc-16"], ["fast", "fast", "branches"], 45, [330, 140, 700]),
    ("ZooKeeper", ["adhoc-06", "adhoc-02", "adhoc-11"], ["fast", "branches", "branches"], 30, [210, 180, 300]),
    ("HBase", ["adhoc-21", "adhoc-35", "adhoc-12"], ["fast", "fast", "branches"], 45, [160, 900, 2600]),
    ("Solr", ["adhoc-13", "adhoc-10", "adhoc-14"], ["fast", "branches", "branches"], 45, [450, 400, 800]),
]


def smooth(y, w):
    if w < 2:
        return y
    x = np.arange(-3 * w, 3 * w + 1)
    g = np.exp(-0.5 * (x / w) ** 2)
    g /= g.sum()
    pad = np.pad(y, 3 * w, mode="edge")
    return np.convolve(pad, g, mode="same")[3 * w:-3 * w]


def curve(kind, level, k, t, window):
    if kind == "fast":
        tau = 0.6 * window / k ** 0.6
        return level * (1 - np.exp(-(t / tau) ** 2))
    a = level * k ** 0.55
    return a * t / (t + 0.6 * window) * 1.6  # a at t = window


def main(out):
    fig, axes = plt.subplots(3, 4, figsize=(16, 10))
    for col, (system, labels, kinds, window, levels) in enumerate(PANELS):
        t = np.linspace(0, window, 400)
        for row in range(3):
            ax = axes[row][col]
            ends = []
            for k in K:
                y = curve(kinds[row], levels[row], k, t, window)
                y = smooth(y, int(0.05 * len(t)))
                y[0] = 0
                ax.plot(t, y, color=COLORS[k], lw=2.4, label="%d machine%s" % (k, "" if k == 1 else "s"))
                ends.append((k, y[-1]))
            # end labels: machine counts that meet share one label
            groups = []
            for k, v in ends:
                for g in groups:
                    if abs(g[1] - v) < 0.02 * max(e[1] for e in ends):
                        g[0].append(k)
                        break
                else:
                    groups.append([[k], v])
            for ks, v in groups:
                ax.text(window * 1.03, v, ", ".join(str(k) for k in ks), va="center", fontsize=11, color="#333", clip_on=False)
            ax.set_title(("%s\n" % system if row == 0 else "") + labels[row], loc="left", fontsize=13)
            ax.set_xlim(0, window)
            ax.set_xticks([0, window / 3, 2 * window / 3, window] if window == 45 else [0, 10, 20, 30])
            ax.set_ylim(0)
            for s in ("top", "right"):
                ax.spines[s].set_visible(False)
            ax.grid(axis="y", color="#eee")
    handles, labels = axes[0][0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper right", bbox_to_anchor=(0.985, 0.995), ncol=4, frameon=False, fontsize=13)
    fig.supxlabel("Exploration time (minutes)", fontsize=14)
    fig.supylabel("New unique region paths", fontsize=14)
    fig.text(0.5, 0.5, "MOCK-UP: synthetic target shape, not measured data", ha="center", va="center", fontsize=40, color="red", alpha=0.25, rotation=20)
    fig.text(0.01, 0.005, "mockup_4x3.py: every curve is a formula (see the file); drawn 2026-11-08 to show the intended shape while the runs finish.", fontsize=9, color="red")
    fig.subplots_adjust(left=0.07, right=0.965, top=0.9, bottom=0.08, hspace=0.5, wspace=0.38)
    for ext in ("pdf", "png"):
        fig.savefig("%s.%s" % (out, ext), dpi=130)
    print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "scaling-4x3-mockup")
