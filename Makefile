PY := .venv/bin/python
RUN := runs/demo

.PHONY: help setup demo test clean redacted probe0 check1 phase2
.DEFAULT_GOAL := help

# The list is derived from the `## ` comments below, so it cannot drift out of date the way a
# hand-maintained block would (the same reasoning as binding a recording to its schema).
help:  ## Show this list
	@echo 'reorg-agent — make <target>   (add LIVE=1 for a real model call)'
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  %-10s %s\n", $$1, $$2}'

setup:  ## Create .venv and install requirements
	python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt

phase2:  ## Extract the fixture message and diff against the answer key (LIVE=1 calls the model and re-records)
	$(PY) -m reorg.cli intake fixtures/msg_jordan.txt --run runs/phase2 $(if $(LIVE),--live --record,)
	PYTHONPATH=. $(PY) probes/phase2_diff.py runs/phase2

# Full demo arc. Keyless by default (replay of a recorded real model response).
# LIVE=1 makes the real call (needs ANTHROPIC_API_KEY in .env).
demo:  ## The whole arc: intake -> validate -> refused approval -> resolve -> approve -> compile
	$(PY) -m reorg.cli intake   fixtures/msg_jordan.txt --run $(RUN) $(if $(LIVE),--live,)
	$(PY) -m reorg.cli validate $(RUN)
	-$(PY) -m reorg.cli approve  $(RUN) --as finance-approver
	$(PY) -m reorg.cli validate $(RUN) --resolve 2.worker=10422 --resolve 1.target_cc=4410
	$(PY) -m reorg.cli approve  $(RUN) --as finance-approver
	$(PY) -m reorg.cli compile  $(RUN)

test:  ## Run the test suite
	$(PY) -m pytest -q

check1:  ## Validate the answer key and show every span beside the words it quotes
	PYTHONPATH=. $(PY) probes/phase1_check.py

probe0:  ## Show the contracts accepting valid shapes and refusing bad ones
	PYTHONPATH=. $(PY) probes/phase0.py

redacted:  ## Print the redacted message with character offsets
	$(PY) -c "from reorg import intake, redact; r,_=redact.redact(intake.capture(\"fixtures/msg_jordan.txt\")); t=r.text; print(t); print(); [print(f\"{i:4} {t[i:i+40]!r}\") for i in range(0,len(t),40)]"

clean:  ## Delete generated run directories
	rm -rf runs/demo runs/phase2
