# pumpfun-top5-forecast-01

A deterministic forecast entry for the five largest newly launched pump.fun
Solana coins by market cap at the task's future answer reads.

`main.py` scores coins from the latest historical chart using log market cap,
30-minute and 1-hour capped log-growth, and a small completed-pool bonus. It
uses place-shifted softmax probabilities over twelve candidates while reserving
35% unnamed probability mass for coins launched after history ends. Size
probabilities are normal distributions over the task-supplied log-cap bins.

Run locally with Python 3.13:

```sh
MAKEFUN_INPUT_DIR=/path/to/input MAKEFUN_OUTPUT_DIR=/path/to/output python3 main.py
```

The program reads `task.json` and `history.ndjson`, then writes
`forecast.json` to the output directory. It uses the Python standard library
only and is deterministic for identical input.
