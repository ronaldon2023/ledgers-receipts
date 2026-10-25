PY := .venv/bin/python

.PHONY: setup test reset replay demo receipt

setup:
	./setup.sh

test:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .
	$(PY) -m pytest

reset:
	$(PY) -m bakery.seed
	rm -f logs/chain.jsonl

replay:
	$(PY) scripts/replay.py

demo:
	@echo "TODO: live run (see the build plan, End-to-end tests)"

receipt:
	$(PY) -m receipts.verify
	$(PY) render/render.py receipt.json -o receipt.html
