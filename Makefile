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
	$(PY) -m reorg.cli validate $(RUN) --resolve 2.worker=10422 --resolve 1.target_cc=4410
	$(PY) -m reorg.cli approve  $(RUN) --as finance-approver
	$(PY) -m reorg.cli compile  $(RUN)

# Re-record the model response used by replay (LIVE call).
record:
	$(PY) -m reorg.cli intake fixtures/msg_jordan.txt --run runs/record --live --record

test:
	$(PY) -m pytest -q

clean:
	rm -rf runs/demo runs/record

# Print the redacted Jordan message with character offsets (for writing intent_expected.json spans).
redacted:
	$(PY) -c "from reorg import intake, redact; r,_=redact.redact(intake.capture(\"fixtures/msg_jordan.txt\")); t=r.text; print(t); print(); [print(f\"{i:4} {t[i:i+40]!r}\") for i in range(0,len(t),40)]"

probe0:
	PYTHONPATH=. $(PY) probes/phase0.py

check1:
	PYTHONPATH=. $(PY) probes/phase1_check.py

# Phase 2: run the extractor on the fixture (replay by default; LIVE=1 makes the real call and records it), then diff.
phase2:
	$(PY) -m reorg.cli intake fixtures/msg_jordan.txt --run runs/phase2 $(if $(LIVE),--live --record,)
	PYTHONPATH=. $(PY) probes/phase2_diff.py runs/phase2
