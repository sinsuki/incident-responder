.PHONY: demo test eval

PYTHON ?= python

demo:
	$(PYTHON) scripts/demo.py

test:
	$(PYTHON) -m pytest

eval:
	$(PYTHON) -m orchestrator.eval
