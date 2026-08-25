# IaC/CD Understanding Benchmark
# Usage: make run MODEL=claude-sonnet-4-5-20250929

SHELL := bash
PYTHON := .venv/bin/python3
RESULTS := results

.PHONY: deps test run report run-e2e run-cold compare

deps:
	($(PYTHON) -m pip install -e . -e ".[dev]")

test:
	($(PYTHON) -m pytest tests/ -v)

# Run benchmark for a single model
# Make run MODEL=claude-sonnet-4-5-20250929 STACK=knr-ops
# Make run MODEL=claude-sonnet-4-5-20250929 STACK=all TASK=T2-generate
# Make run MODEL=claude-sonnet-4-5-20250929 PROVIDER=openai-compat BASE_URL=http://localhost:8000
# Make run MODEL=claude-opus-5 JUDGE=1   (idiom axis via rubric judge; costs extra API calls)
run:
	($(PYTHON) -m bench.runner \
		--model $(MODEL) \
		--model-provider $(or $(PROVIDER),anthropic) \
		$(if $(BASE_URL),--model-args --base-url $(BASE_URL)) \
		$(if $(STACK),--stack $(STACK)) \
		$(if $(TASK),--task $(TASK)) \
		$(if $(TASKS),--tasks $(TASKS)) \
		-k $(or $(K),3) \
		--condition $(or $(CONDITION),warm) \
		$(if $(JUDGE),--judge) \
		$(if $(JUDGE_MODEL),--judge-model $(JUDGE_MODEL)) \
		$(if $(API_KEY),--api-key $(API_KEY)))

# Run with e2e validation (requires kind + docker)
run-e2e:
	($(PYTHON) -m bench.runner \
		--model $(MODEL) \
		--model-provider $(or $(PROVIDER),anthropic) \
		$(if $(BASE_URL),--model-args --base-url $(BASE_URL)) \
		$(if $(STACK),--stack $(STACK)) \
		$(if $(TASK),--task $(TASK)) \
		-k $(or $(K),3) \
		--condition $(or $(CONDITION),warm) \
		--e2e \
		$(if $(API_KEY),--api-key $(API_KEY)))

# Generate markdown report from results
report:
	($(PYTHON) -m bench.report $(if $(OUTPUT),--output $(OUTPUT)))

# Generate comparative report across models
compare:
	($(PYTHON) -m bench.report --compare $(RESULTS)/*)

# Run cold condition (no docs injected)
run-cold:
	($(PYTHON) -m bench.runner \
		--model $(MODEL) \
		--model-provider $(or $(PROVIDER),anthropic) \
		$(if $(BASE_URL),--model-args --base-url $(BASE_URL)) \
		$(if $(STACK),--stack $(STACK)) \
		-k $(or $(K),3) \
		--condition cold \
		$(if $(API_KEY),--api-key $(API_KEY)))
