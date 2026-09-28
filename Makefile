PY := .venv/bin/python
PYTHON ?= python3
RUN := runs/demo

.PHONY: help setup demo test clean redacted extract guard
.DEFAULT_GOAL := help

# The listing below is built from the `###` and `## ` comments in this file, so it cannot drift
# out of date the way a hand-written block would.
help:
	@echo ''
	@echo 'reorg-agent —  make <target>'
	@echo ''
	@awk 'BEGIN{FS=":.*?## "} \
		/^### /{printf "\n%s\n", substr($$0,5)} \
		/^[a-zA-Z0-9_-]+:.*?## /{printf "  %-11s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ''
	@echo 'Everything runs without an API key by replaying a recorded real response.'
	@echo 'Add LIVE=1 to extract or demo to make a real call instead (needs .env).'
	@echo ''

# Fails early with something readable, instead of "no such file or directory".
guard:
	@test -x $(PY) || { echo 'No virtualenv here yet. Run:  make setup'; exit 1; }

### Show the system working

extract: guard  ## The main beat: read the message, then check the result against the answer key
	$(PY) -m reorg.cli capture fixtures/msg_jordan.txt --run runs/extract $(if $(LIVE),--live --record,)
	PYTHONPATH=. $(PY) probes/diff_extraction.py runs/extract

demo: guard  ## The whole arc, capture through approval to a compiled plan
	$(PY) -m reorg.cli capture  fixtures/msg_jordan.txt --run $(RUN) $(if $(LIVE),--live,)
	$(PY) -m reorg.cli validate $(RUN)
	-$(PY) -m reorg.cli approve  $(RUN) --as dana.finance --role finance
	$(PY) -m reorg.cli validate $(RUN) --resolve 1.target_cc=4410
	$(PY) -m reorg.cli approve  $(RUN) --as dana.finance --role finance
	$(PY) -m reorg.cli compile  $(RUN)

### While building

test: guard  ## Run the test suite
	$(PY) -m pytest -q

redacted: guard  ## Print the message as the model sees it, with character positions
	$(PY) -c "from reorg import intake, redact; r,_=redact.redact(intake.capture(\"fixtures/msg_jordan.txt\")); t=r.text; print(t); print(); [print(f\"{i:4} {t[i:i+40]!r}\") for i in range(0,len(t),40)]"

### Setting up

setup:  ## Create .venv and install the pinned requirements. Run this first, on any machine
	@$(PYTHON) -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
		|| { echo 'Python 3.10 or newer is required; found' "$$($(PYTHON) --version 2>&1)"; exit 1; }
	$(PYTHON) -m venv .venv && .venv/bin/pip install -q -r requirements.txt
	@echo 'Ready. Try:  make extract'

clean:  ## Delete generated run directories
	rm -rf runs/demo runs/extract
