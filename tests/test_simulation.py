"""
Unit Tests for Mobile IP Simulation
Tests: MN/HA/FA components, handoff procedure, tunneling, packet delivery
"""

import sys
import os
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from src.mobile_ip import HomeAgent, ForeignAgent, MobileNode, Packet, NodeState
from src.simulation import (
    SimulationConfig,
    NetworkSimulator,
    SessionSimulator,
    get_effective_handoff_interval,
)
from src.evaluation import build_topology


class TestHomeAgent(unittest.TestCase):

    def setUp(self):
        self.ha = HomeAgent("10.0.0.1", "10.0.0.0/24")

    def test_register_and_lookup(self):
        self.ha.register("10.0.0.100", "192.168.1.1", "192.168.1.1")
        entry = self.ha.get_binding("10.0.0.100")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.care_of_address, "192.168.1.1")

    def test_deregister(self):
        self.ha.register("10.0.0.100", "192.168.1.1", "192.168.1.1")
        self.ha.deregister("10.0.0.100")
        self.assertIsNone(self.ha.get_binding("10.0.0.100"))

    def test_tunnel_registered_mn(self):
        self.ha.register("10.0.0.100", "192.168.1.1", "192.168.1.1")
        pkt = Packet(1, "172.16.0.50", "10.0.0.100", "data")
        tunneled = self.ha.intercept_and_tunnel(pkt)
        self.assertIsNotNone(tunneled)
        self.assertEqual(tunneled.dst_ip, "192.168.1.1")
        self.assertIn("TUNNELED", tunneled.payload)

    def test_home_network_passthrough_for_unknown_mn(self):
        pkt = Packet(1, "172.16.0.50", "10.0.0.200", "data")
        tunneled = self.ha.intercept_and_tunnel(pkt)
        self.assertIsNotNone(tunneled)
        self.assertEqual(tunneled.dst_ip, "10.0.0.200")

    def test_binding_validity(self):
        self.ha.register("10.0.0.100", "192.168.1.1", "192.168.1.1", lifetime=0.1)
        time.sleep(0.2)
        entry = self.ha.get_binding("10.0.0.100")
        self.assertFalse(entry.is_valid())

    def test_direct_delivery_to_home_network(self):
        pkt = Packet(1, "172.16.0.50", "10.0.0.100", "data")
        routed = self.ha.intercept_and_tunnel(pkt)
        self.assertIs(routed, pkt)


class TestForeignAgent(unittest.TestCase):

    def setUp(self):
        self.ha = HomeAgent("10.0.0.1", "10.0.0.0/24")
        self.fa = ForeignAgent("192.168.1.1", "192.168.1.0/24", 1)

    def test_advertise(self):
        adv = self.fa.advertise()
        self.assertEqual(adv["fa_address"], "192.168.1.1")
        self.assertEqual(adv["network_id"], 1)

    def test_register_visitor(self):
        result = self.fa.register_visitor("10.0.0.100", self.ha)
        self.assertTrue(result)
        status = self.fa.status()
        self.assertIn("10.0.0.100", status["visiting_nodes"])

    def test_deregister_visitor(self):
        self.fa.register_visitor("10.0.0.100", self.ha)
        self.fa.deregister_visitor("10.0.0.100")
        self.assertNotIn("10.0.0.100", self.fa.status()["visiting_nodes"])


class TestMobileNode(unittest.TestCase):

    def setUp(self):
        self.ha = HomeAgent("10.0.0.1", "10.0.0.0/24")
        self.fa1 = ForeignAgent("192.168.1.1", "192.168.1.0/24", 1)
        self.fa2 = ForeignAgent("192.168.2.1", "192.168.2.0/24", 2)
        self.mn = MobileNode("10.0.0.100", self.ha)

    def test_initial_state(self):
        self.assertEqual(self.mn.state, NodeState.HOME)
        self.assertIsNone(self.mn.current_fa)

    def test_handoff_to_fa(self):
        self.mn.perform_handoff(self.fa1)
        self.assertEqual(self.mn.state, NodeState.FOREIGN)
        self.assertEqual(self.mn.current_fa.network_id, 1)
        self.assertEqual(self.mn.handoff_count, 1)

    def test_sequential_handoff(self):
        self.mn.perform_handoff(self.fa1)
        self.mn.perform_handoff(self.fa2)
        self.assertEqual(self.mn.handoff_count, 2)
        self.assertEqual(self.mn.current_fa.network_id, 2)

    def test_same_fa_is_not_counted_as_new_handoff(self):
        first_latency = self.mn.perform_handoff(self.fa1)
        second_latency = self.mn.perform_handoff(self.fa1)
        self.assertGreater(first_latency, 0)
        self.assertEqual(second_latency, 0.0)
        self.assertEqual(self.mn.handoff_count, 1)

    def test_return_home(self):
        self.mn.perform_handoff(self.fa1)
        self.mn.return_home()
        self.assertEqual(self.mn.state, NodeState.HOME)
        self.assertIsNone(self.mn.current_fa)

    def test_movement_detection(self):
        self.assertTrue(self.mn.detect_movement(self.fa1))
        self.mn.perform_handoff(self.fa1)
        self.assertFalse(self.mn.detect_movement(self.fa1))
        self.assertTrue(self.mn.detect_movement(self.fa2))

    def test_send_receive(self):
        pkt = self.mn.send_packet("172.16.0.50", "test")
        self.assertEqual(self.mn.status()["packets_sent"], 1)
        self.mn.receive_packet(pkt)
        self.assertEqual(self.mn.status()["packets_received"], 1)


class TestNetworkSimulator(unittest.TestCase):

    def test_normal_delivery(self):
        config = SimulationConfig(base_packet_loss_prob=0.0)
        net = NetworkSimulator(config)
        pkt = Packet(1, "a", "b", "data")
        delivered, delay = net.transmit(pkt)
        self.assertTrue(delivered)
        self.assertGreater(delay, 0)

    def test_total_loss(self):
        config = SimulationConfig(base_packet_loss_prob=1.0)
        net = NetworkSimulator(config)
        pkt = Packet(1, "a", "b", "data")
        delivered, delay = net.transmit(pkt)
        self.assertFalse(delivered)

    def test_handoff_state(self):
        config = SimulationConfig(handoff_loss_window=1.0)
        net = NetworkSimulator(config)
        net.set_handoff_state(True)
        self.assertTrue(net.is_in_handoff_window())
        net.set_handoff_state(False)
        self.assertFalse(net.is_in_handoff_window())


class TestIntegration(unittest.TestCase):

    def test_full_topology_build(self):
        topo = build_topology(3)
        self.assertIsNotNone(topo["ha"])
        self.assertEqual(len(topo["fas"]), 3)
        self.assertIsNotNone(topo["mn"])

    def test_end_to_end_packet_flow(self):
        """Test complete packet flow: correspondent → HA → FA → MN."""
        ha = HomeAgent("10.0.0.1", "10.0.0.0/24")
        fa = ForeignAgent("192.168.1.1", "192.168.1.0/24", 1)
        mn = MobileNode("10.0.0.100", ha)

        # MN moves to foreign network
        mn.perform_handoff(fa)

        # Correspondent sends packet
        pkt = Packet(1, "172.16.0.50", "10.0.0.100", "Hello")
        tunneled = ha.intercept_and_tunnel(pkt)
        self.assertIsNotNone(tunneled)

        # FA delivers to MN
        fa.decapsulate_and_deliver(tunneled, mn)
        self.assertEqual(mn.status()["packets_received"], 1)

    def test_session_metrics_computed(self):
        topo = build_topology(2)
        ha, fas, mn, corr = topo["ha"], topo["fas"], topo["mn"], topo["correspondent"]
        config = SimulationConfig(
            num_packets=10,
            handoff_interval=0.05,
            packet_interval=0.02,
            base_handoff_latency_ms=5.0,
            handoff_loss_window=0.01,
            base_packet_loss_prob=0.0,
            handoff_loss_prob=0.0,
        )
        net_sim = NetworkSimulator(config)
        session = SessionSimulator(mn, ha, fas, config, net_sim)
        session.run_session(corr, "sequential")
        metrics = session.compute_metrics()
        self.assertIn("packet_loss_rate", metrics)
        self.assertIn("session_continuity_pct", metrics)
        self.assertIn("avg_delay_ms", metrics)

    def test_inflight_packet_forwarded_to_new_fa(self):
        ha = HomeAgent("10.0.0.1", "10.0.0.0/24")
        fa1 = ForeignAgent("192.168.1.1", "192.168.1.0/24", 1)
        fa2 = ForeignAgent("192.168.2.1", "192.168.2.0/24", 2)
        mn = MobileNode("10.0.0.100", ha)
        config = SimulationConfig(base_packet_loss_prob=0.0, handoff_loss_prob=0.0)
        net_sim = NetworkSimulator(config)
        session = SessionSimulator(mn, ha, [fa1, fa2], config, net_sim)

        mn.perform_handoff(fa1)
        pkt = Packet(1, "172.16.0.50", "10.0.0.100", "Hello")
        tunneled = ha.intercept_and_tunnel(pkt)

        mn.perform_handoff(fa2)
        delivered, delay = session._deliver_tunneled_packet(tunneled)

        self.assertTrue(delivered)
        self.assertGreater(delay, 0)
        self.assertEqual(fa2.status()["packets_received"], 1)
        self.assertEqual(mn.status()["packets_received"], 1)

    def test_ping_pong_uses_effective_interval(self):
        self.assertEqual(get_effective_handoff_interval("sequential", 2.0), 2.0)
        self.assertEqual(get_effective_handoff_interval("ping_pong", 2.0), 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
