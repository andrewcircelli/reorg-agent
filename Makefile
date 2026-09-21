PY := .venv/bin/python
RUN := runs/demo

.PHONY: setup demo record test clean

setup:
	python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt

# Full demo arc. Keyless by default (replay of a recorded real model response).
# LIVE=1 makes the real call (needs ANTHROPIC_API_KEY in .env).
demo:
	$(PY) -m reorg.cli intake   fixtures/msg_jordan.txt --run $(RUN) $(if $(LIVE),--live,)
	$(PY) -m reorg.cli validate $(RUN)
	-$(PY) -m reorg.cli approve  $(RUN) --as finance-approver
	$(PY) -m reorg.cli validate $(RUN) --resolve worker=10422 --resolve target_cc=4410
	$(PY) -m reorg.cli approve  $(RUN) --as finance-approver
	$(PY) -m reorg.cli compile  $(RUN)

# Re-record the model response used by replay (LIVE call).
record:
	$(PY) -m reorg.cli intake fixtures/msg_jordan.txt --run runs/record --live --record fixtures/recorded/msg_jordan.json

test:
	$(PY) -m pytest -q

clean:
	rm -rf runs/demo runs/record
