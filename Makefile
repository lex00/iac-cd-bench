# IaC/CD Understanding Benchmark
# Usage: make run MODEL=claude-sonnet-4-20250514

SHELL := bash
VENV := .venv/bin/activate
RESULTS := results

.PHONY: deps test run report run-e2e

deps:
	($(VENV) && pip install -e . -e ".[dev]")

test:
	($(VENV) && python3 -m pytest tests/ -v)

# Run benchmark for a single model
# Make run MODEL=claude-sonnet-4-20250514 STACK=knr-ops
# Make run MODEL=claude-sonnet-4-20250514 STACK=all TASK=T2-generate
# Make run MODEL=claude-sonnet-4-20250514 PROVIDER=openai-compat BASE_URL=http://localhost:8000
run:
	($(VENV) && python3 -m bench.runner \
		--model $(MODEL) \
		--model-provider $(or $(PROVIDER),anthropic) \
		$(if $(BASE_URL),--model-args --base-url $(BASE_URL)) \
		$(if $(STACK),--stack $(STACK)) \
		$(if $(TASK),--task $(TASK)) \
		$(if $(TASKS),--tasks $(TASKS)) \
		-k $(or $(K),3) \
		--condition $(or $(CONDITION),warm))

# Run with e2e validation (requires kind + docker)
run-e2e:
	($(VENV) && python3 -m bench.runner \
		--model $(MODEL) \
		--model-provider $(or $(PROVIDER),anthropic) \
		$(if $(BASE_URL),--model-args --base-url $(BASE_URL)) \
		$(if $(STACK),--stack $(STACK)) \
		$(if $(TASK),--task $(TASK)) \
		-k $(or $(K),3) \
		--condition $(or $(CONDITION),warm) \
		--e2e)

# Generate markdown report from results
report:
	($(VENV) && python3 -m bench.report $(if $(OUTPUT),--output $(OUTPUT)))

# Generate comparative report across models
compare:
	($(VENV) && python3 -m bench.report --compare $(RESULTS)/*)

# Run cold condition (no docs injected) — for knr-ops documentation dependency tests
run-cold:
	($(VENV) && python3 -m bench.runner \
		--model $(MODEL) \
		--model-provider $(or $(PROVIDER),anthropic) \
		$(if $(BASE_URL),--model-args --base-url $(BASE_URL)) \
		$(if $(STACK),--stack $(STACK)) \
		-k $(or $(K),3) \
		--condition cold)
