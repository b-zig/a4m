# Convenience targets. Everything also works as plain `python3 -m a4m ...`.
PY ?= python3

.PHONY: help validate build sas test check-mermaid schema rules-refresh

help:
	@echo "make validate | build | sas | test | check-mermaid | schema | rules-refresh"

validate:
	$(PY) -m a4m validate -w

build:
	$(PY) -m a4m build

sas:
	$(PY) -m a4m sas

test:
	$(PY) -m unittest discover -s tests -t .

check-mermaid:
	npm ci --prefix tools --silent && node tools/check-mermaid.mjs docs

schema:
	$(PY) -m a4m schema --write

ARCHI_RAW := https://raw.githubusercontent.com/archimatetool/archi/master/com.archimatetool.model/model
rules-refresh:
	curl -sSf -o rules/archimate-3.2/relationships.xml $(ARCHI_RAW)/relationships.xml
	curl -sSf -o rules/archimate-3.2/relationships-keys.xml $(ARCHI_RAW)/relationships-keys.xml
	$(MAKE) test
