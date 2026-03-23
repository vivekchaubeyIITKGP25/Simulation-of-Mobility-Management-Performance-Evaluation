import json
import os
import sys

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import numpy as np
    HAS_MPL = True
except ImportError:
    HAS_MPL = False
    print("[WARNING] matplotlib not installed. Install with: pip install matplotlib")


def load_results(results_dir: str = "results") -> list:
    agg = os.path.join(results_dir, "aggregate_results.json")
    if os.path.exists(agg):
        with open(agg) as f:
            return json.load(f)
    # Load individual files
    results = []
    for fname in os.listdir(results_dir):
        if fname.endswith(".json") and fname != "aggregate_results.json":
            with open(os.path.join(results_dir, fname)) as f:
                results.append(json.load(f))
    return results


def plot_all(results: list, output_dir: str = "results"):
    if not HAS_MPL:
        print("Matplotlib required for plotting.")
        return

    os.makedirs(output_dir, exist_ok=True)
    patterns = sorted(set(r["pattern"] for r in results))
    colors = {"sequential": "#2196F3", "random_walk": "#FF5722", "ping_pong": "#4CAF50"}
    markers = {"sequential": "o", "random_walk": "s", "ping_pong": "^"}

    # Group by pattern
    def get_series(pattern, key):
        data = [(r["mobility_rate"], r[key]) for r in results
                if r["pattern"] == pattern and key in r]
        data.sort(key=lambda x: x[0])
        return [d[0] for d in data], [d[1] for d in data]

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle("Mobile IP Simulation — Performance Evaluation", fontsize=15, fontweight='bold')

    # Plot 1: Mobility rate vs Packet loss
    ax = axes[0, 0]
    for p in patterns:
        x, y = get_series(p, "packet_loss_rate")
        ax.plot(x, y, color=colors[p], marker=markers[p], label=p, linewidth=2, markersize=7)
    ax.set_title("Mobility Rate vs Packet Loss Rate")
    ax.set_xlabel("Mobility Rate (handoffs/sec)")
    ax.set_ylabel("Packet Loss (%)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.set_facecolor('#f8f9fa')

    # Plot 2: Mobility rate vs Handoff latency
    ax = axes[0, 1]
    for p in patterns:
        x, y = get_series(p, "handoff_latency_avg_ms")
        ax.plot(x, y, color=colors[p], marker=markers[p], label=p, linewidth=2, markersize=7)
    ax.set_title("Mobility Rate vs Avg Handoff Latency")
    ax.set_xlabel("Mobility Rate (handoffs/sec)")
    ax.set_ylabel("Avg Handoff Latency (ms)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.set_facecolor('#f8f9fa')

    # Plot 3: Mobility rate vs Session continuity
    ax = axes[1, 0]
    for p in patterns:
        x, y = get_series(p, "session_continuity_pct")
        ax.plot(x, y, color=colors[p], marker=markers[p], label=p, linewidth=2, markersize=7)
    ax.set_title("Mobility Rate vs Session Continuity")
    ax.set_xlabel("Mobility Rate (handoffs/sec)")
    ax.set_ylabel("Session Continuity (%)")
    ax.set_ylim([0, 105])
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.set_facecolor('#f8f9fa')

    # Plot 4: Avg delay comparison (grouped bar)
    ax = axes[1, 1]
    intervals = sorted(set(r["handoff_interval"] for r in results))
    x_pos = np.arange(len(intervals))
    width = 0.25
    for i, p in enumerate(patterns):
        vals = []
        for interval in intervals:
            matched = [r for r in results if r["pattern"] == p and r["handoff_interval"] == interval]
            vals.append(matched[0]["avg_delay_ms"] if matched else 0)
        ax.bar(x_pos + i * width, vals, width, label=p, color=colors[p], alpha=0.85)
    ax.set_title("Avg Packet Delay by Pattern & Interval")
    ax.set_xlabel("Handoff Interval (s)")
    ax.set_ylabel("Avg Delay (ms)")
    ax.set_xticks(x_pos + width)
    ax.set_xticklabels([str(i) for i in intervals])
    ax.legend()
    ax.grid(True, alpha=0.3, axis='y')
    ax.set_facecolor('#f8f9fa')

    plt.tight_layout()
    out = os.path.join(output_dir, "performance_plots.png")
    plt.savefig(out, dpi=150, bbox_inches='tight')
    print(f"[PLOT] Saved: {out}")
    plt.close()

    # Plot 5: Handoff procedure timeline diagram
    fig2, ax2 = plt.subplots(figsize=(12, 5))
    ax2.set_xlim(0, 10)
    ax2.set_ylim(-0.5, 3.5)
    ax2.set_yticks([0, 1, 2, 3])
    ax2.set_yticklabels(["Correspondent", "Home Agent", "Foreign Agent", "Mobile Node"], fontsize=11)
    ax2.set_xlabel("Time (simulated)", fontsize=11)
    ax2.set_title("Mobile IP Handoff Sequence Diagram", fontsize=13, fontweight='bold')
    ax2.set_facecolor('#f0f4f8')
    ax2.grid(True, axis='x', alpha=0.3)

    # Lifelines
    for y in [0, 1, 2, 3]:
        ax2.axhline(y=y, color='gray', linestyle='--', alpha=0.3)

    # Messages (arrows)
    msgs = [
        (0.5, 3, 2, "FA Advertisement", "#42a5f5"),
        (1.5, 3, 2, "Registration Request (MN→FA)", "#66bb6a"),
        (2.0, 2, 1, "Registration Relay (FA→HA)", "#66bb6a"),
        (2.5, 1, 2, "Registration Reply (HA→FA)", "#ffa726"),
        (3.0, 2, 3, "Registration Reply (FA→MN)", "#ffa726"),
        (4.0, 0, 1, "Data Packet", "#ef5350"),
        (4.5, 1, 2, "Tunneled Packet (IP-in-IP)", "#ab47bc"),
        (5.0, 2, 3, "Decapsulated Delivery", "#26c6da"),
    ]

    for t, src_y, dst_y, label, color in msgs:
        ax2.annotate("",
                     xy=(t + 0.8, dst_y), xytext=(t, src_y),
                     arrowprops=dict(arrowstyle="-|>", color=color, lw=1.8))
        mid_y = (src_y + dst_y) / 2
        ax2.text(t + 0.42, mid_y + 0.08, label, fontsize=7.5,
                 color=color, ha='center', fontweight='bold')

    out2 = os.path.join(output_dir, "handoff_sequence.png")
    plt.tight_layout()
    plt.savefig(out2, dpi=150, bbox_inches='tight')
    print(f"[PLOT] Saved: {out2}")
    plt.close()


def main():
    results_dir = sys.argv[1] if len(sys.argv) > 1 else "results"
    results = load_results(results_dir)
    if not results:
        print(f"No results found in {results_dir}. Run main.py --full first.")
        return
    print(f"[PLOT] Loaded {len(results)} scenario results")
    plot_all(results, results_dir)


if __name__ == "__main__":
    main()
