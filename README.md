# Mobile IP and Handoff Mechanism Simulation

Simple simulation of Mobile IP with:
- Mobile Node (MN)
- Home Agent (HA)
- Foreign Agents (FA)
- handoff, tunneling, delay, and packet loss

## Files
- `main.py` : run the simulation
- `visualize.py` : generate graphs from saved results
- `src/` : core implementation
- `tests/` : unit tests

## Install
```bash
python -m pip install -r requirements.txt
```

## Run
Quick demo:
```bash
python main.py --quick
```

Single scenario:
```bash
python main.py --pattern sequential --interval 2.0 --packets 30
```

Full evaluation:
```bash
python main.py --full
```

Generate plots:
```bash
python visualize.py
```

Run tests:
```bash
python -m pytest tests -v
```

## Patterns
- `sequential`
- `random_walk`
- `ping_pong`

## Output
Running the program creates:
- `logs/simulation.log`
- `results/scenario_*.json`
- `results/aggregate_results.json`
- `results/performance_plots.png`
- `results/handoff_sequence.png`
