#!/usr/bin/env python3
"""
Mobile IP and Handoff Mechanism Simulation
==========================================
Term Project - Computer Networks

Implements:
 - Mobile IP Architecture (MN, HA, FA)
 - Registration & Tunneling
 - Handoff Simulation (sequential, random walk, ping-pong)
 - Packet Loss & Delay Modeling
 - Performance Evaluation

Usage:
    python main.py              # Full evaluation (all patterns, all mobility rates)
    python main.py --quick      # Quick demo with one scenario
    python main.py --pattern sequential --interval 2.0 --packets 20
"""

import sys
import os
import argparse
import logging
import time
import json

sys.path.insert(0, os.path.dirname(__file__))

from src.mobile_ip import HomeAgent, ForeignAgent, MobileNode
from src.simulation import SimulationConfig, NetworkSimulator, SessionSimulator
from src.evaluation import evaluate_mobility_vs_performance, run_single_scenario, print_summary_table, build_topology

# Setup logging
os.makedirs("logs", exist_ok=True)
os.makedirs("results", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("logs/simulation.log", encoding="utf-8"),
        logging.StreamHandler()
    ],
    force=True
)
logger = logging.getLogger(__name__)


def demo_basic_architecture():
    """Demonstrate core Mobile IP architecture."""
    print("\n" + "="*60)
    print("DEMO: Mobile IP Architecture")
    print("="*60)
    demo_handoff_delay_ms = 20.0

    topo = build_topology(3)
    ha, fas, mn, correspondent = topo["ha"], topo["fas"], topo["mn"], topo["correspondent"]

    print(f"\n[Topology]")
    print(f"  Home Agent    : {ha.address} ({ha.network})")
    for fa in fas:
        print(f"  Foreign Agent {fa.network_id}: {fa.address} ({fa.network})")
    print(f"  Mobile Node   : {mn.home_address}")
    print(f"  Correspondent : {correspondent}")

    print("\n[Step 1] MN at Home Network")
    print(f"  MN state: {mn.status()['state']}")

    print("\n[Step 2] MN moves to FA-1 (First Handoff)")
    lat1 = mn.perform_handoff(fas[0], signaling_delay_ms=demo_handoff_delay_ms)
    print(f"  Handoff latency: ~{lat1:.1f} ms")
    print(f"  MN state: {mn.status()['state']}, CoA: {mn.current_fa.address}")

    print("\n[Step 3] HA Tunneling Demo")
    from src.mobile_ip import Packet
    pkt = Packet(1, correspondent, mn.home_address, "Hello MN!")
    tunneled = ha.intercept_and_tunnel(pkt)
    if tunneled:
        print(f"  Original: {pkt}")
        print(f"  Tunneled: {tunneled}")

    print("\n[Step 4] MN moves to FA-2 (Second Handoff)")
    lat2 = mn.perform_handoff(fas[1], signaling_delay_ms=demo_handoff_delay_ms)
    print(f"  Handoff latency: ~{lat2:.1f} ms")
    print(f"  MN state: {mn.status()['state']}, CoA: {mn.current_fa.address}")

    print("\n[Step 5] MN returns home")
    mn.return_home()
    print(f"  MN state: {mn.status()['state']}")

    print(f"\n[HA Status]\n  {ha.status()}")
    print(f"\n[MN Status]\n  {mn.status()}")
    print()


def run_full_evaluation():
    """Run full performance evaluation across all patterns and mobility rates."""
    print("\n" + "="*60)
    print("FULL PERFORMANCE EVALUATION")
    print("="*60)
    print("Patterns: sequential, random_walk, ping_pong")
    print("Handoff intervals: 0.5, 1.0, 2.0, 3.0, 5.0 seconds")
    print("This will take ~2-3 minutes...\n")

    results = evaluate_mobility_vs_performance(results_dir="results")
    print_summary_table(results)

    # Key findings
    print("\n[KEY FINDINGS]")
    sorted_by_loss = sorted(results, key=lambda x: x.get("packet_loss_rate", 0), reverse=True)
    print(f"  Highest packet loss: {sorted_by_loss[0]['pattern']} @ "
          f"{sorted_by_loss[0]['handoff_interval']}s interval = "
          f"{sorted_by_loss[0]['packet_loss_rate']}%")

    sorted_by_latency = sorted(results, key=lambda x: x.get("handoff_latency_avg_ms", 0), reverse=True)
    print(f"  Highest handoff latency: {sorted_by_latency[0]['pattern']} @ "
          f"{sorted_by_latency[0]['handoff_interval']}s = "
          f"{sorted_by_latency[0]['handoff_latency_avg_ms']}ms")

    return results


def main():
    parser = argparse.ArgumentParser(description="Mobile IP Simulation")
    parser.add_argument("--quick", action="store_true", help="Quick architecture demo only")
    parser.add_argument("--pattern", default="sequential",
                        choices=["sequential", "random_walk", "ping_pong"])
    parser.add_argument("--interval", type=float, default=2.0, help="Handoff interval (s)")
    parser.add_argument("--packets", type=int, default=20, help="Number of packets")
    parser.add_argument("--full", action="store_true", help="Full evaluation across all scenarios")
    args = parser.parse_args()

    print("\n" + "="*60)
    print("  MOBILE IP AND HANDOFF MECHANISM SIMULATION")
    print("  Term Project - Computer Networks")
    print("="*60)

    # Always show basic architecture demo
    demo_basic_architecture()

    if args.quick:
        print("\n[Quick mode] Architecture demo complete.")
        return

    if args.full:
        run_full_evaluation()
    else:
        # Single scenario
        print(f"\n[Running single scenario: {args.pattern}, interval={args.interval}s, packets={args.packets}]")
        result = run_single_scenario(
            pattern=args.pattern,
            handoff_interval=args.interval,
            num_packets=args.packets,
            results_dir="results"
        )
        print("\n[METRICS]")
        for k, v in result.items():
            if not isinstance(v, dict):
                print(f"  {k}: {v}")

        print(f"\nResults saved to results/")
        print(f"Logs saved to logs/simulation.log")


if __name__ == "__main__":
    main()
