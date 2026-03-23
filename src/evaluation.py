"""Scenario runners and summary helpers."""

import json
import logging
import os
from typing import List, Dict

from src.mobile_ip import HomeAgent, ForeignAgent, MobileNode
from src.simulation import (
    SimulationConfig,
    NetworkSimulator,
    SessionSimulator,
    get_effective_handoff_interval,
)

logger = logging.getLogger(__name__)


def build_topology(num_fas: int = 3) -> Dict:
    """Create the default topology."""
    ha = HomeAgent(address="10.0.0.1", network="10.0.0.0/24")

    fas = []
    for i in range(num_fas):
        fa = ForeignAgent(
            address=f"192.168.{i+1}.1",
            network=f"192.168.{i+1}.0/24",
            network_id=i + 1,
        )
        fas.append(fa)

    mn = MobileNode(home_address="10.0.0.100", ha=ha)
    correspondent = "172.16.0.50"

    return {"ha": ha, "fas": fas, "mn": mn, "correspondent": correspondent}


def run_single_scenario(pattern: str, handoff_interval: float,
                        num_packets: int, results_dir: str) -> Dict:
    """Run one scenario and save its metrics."""
    logger.info(f"\n{'#' * 60}")
    logger.info(
        f"Scenario: pattern={pattern}, handoff_interval={handoff_interval}s, packets={num_packets}"
    )
    logger.info(f"{'#' * 60}")

    topo = build_topology(num_fas=3)
    ha, fas, mn, correspondent = topo["ha"], topo["fas"], topo["mn"], topo["correspondent"]
    effective_interval = max(get_effective_handoff_interval(pattern, handoff_interval), 0.001)

    config = SimulationConfig(
        num_packets=num_packets,
        handoff_interval=handoff_interval,
        packet_interval=0.2,
        base_handoff_latency_ms=15.0 + (10.0 / effective_interval),
        base_packet_loss_prob=0.02,
        handoff_loss_prob=0.20,
    )

    net_sim = NetworkSimulator(config)
    session_sim = SessionSimulator(mn, ha, fas, config, net_sim)

    handoff_latencies = session_sim.run_session(correspondent, mobility_pattern=pattern)
    metrics = session_sim.compute_metrics()

    if handoff_latencies:
        metrics["handoff_latency_avg_ms"] = round(sum(handoff_latencies) / len(handoff_latencies), 2)
        metrics["handoff_latency_max_ms"] = round(max(handoff_latencies), 2)
        metrics["handoff_latency_min_ms"] = round(min(handoff_latencies), 2)
        metrics["total_handoffs"] = len(handoff_latencies)
        metrics["mobility_rate"] = round(1.0 / effective_interval, 3)
    else:
        metrics["handoff_latency_avg_ms"] = 0
        metrics["handoff_latency_max_ms"] = 0
        metrics["handoff_latency_min_ms"] = 0
        metrics["total_handoffs"] = 0
        metrics["mobility_rate"] = 0

    metrics["pattern"] = pattern
    metrics["handoff_interval"] = handoff_interval
    metrics["num_packets"] = num_packets

    metrics["ha_status"] = ha.status()
    metrics["mn_status"] = mn.status()

    fname = f"{results_dir}/scenario_{pattern}_{int(handoff_interval * 10):03d}.json"
    os.makedirs(results_dir, exist_ok=True)
    with open(fname, "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    logger.info(f"[EVAL] Results saved to {fname}")

    return metrics


def evaluate_mobility_vs_performance(results_dir: str = "results") -> List[Dict]:
    """Run the full evaluation matrix."""
    handoff_intervals = [0.5, 1.0, 2.0, 3.0, 5.0]
    patterns = ["sequential", "random_walk", "ping_pong"]
    num_packets = 30

    all_results = []

    for pattern in patterns:
        for interval in handoff_intervals:
            result = run_single_scenario(
                pattern=pattern,
                handoff_interval=interval,
                num_packets=num_packets,
                results_dir=results_dir,
            )
            all_results.append(result)

    aggregate_path = f"{results_dir}/aggregate_results.json"
    with open(aggregate_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    logger.info(f"\n[EVAL] All results saved to {aggregate_path}")

    return all_results


def print_summary_table(results: List[Dict]):
    """Print a compact summary table."""
    print("\n" + "=" * 100)
    print(f"{'PERFORMANCE EVALUATION SUMMARY':^100}")
    print("=" * 100)
    print(
        f"{'Pattern':<15} {'Interval(s)':<12} {'Mob.Rate':<10} {'Handoffs':<10} "
        f"{'HA Lat(ms)':<12} {'Loss%':<8} {'AvgDel(ms)':<12} {'Sess.Cont%':<12}"
    )
    print("-" * 100)

    for r in results:
        print(
            f"{r.get('pattern', ''):<15} "
            f"{r.get('handoff_interval', 0):<12.1f} "
            f"{r.get('mobility_rate', 0):<10.3f} "
            f"{r.get('total_handoffs', 0):<10} "
            f"{r.get('handoff_latency_avg_ms', 0):<12.2f} "
            f"{r.get('packet_loss_rate', 0):<8.2f} "
            f"{r.get('avg_delay_ms', 0):<12.2f} "
            f"{r.get('session_continuity_pct', 0):<12.2f}"
        )
    print("=" * 100)
