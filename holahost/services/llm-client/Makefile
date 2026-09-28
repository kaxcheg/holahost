# llm-client. Everything below `include` is the platform's (holahost/make/common.mk); what is
# here is this service's own values and any target nothing else has.

SVC := llm-client

# A tripwire against an order-of-magnitude drift, not a budget to optimise against: what it
# catches is a transitive dependency, a stray cache directory or a model file that started
# riding along.
MAX_IMAGE_MB := 600

include ../../make/common.mk

.PHONY: validate-registry

# The startup's own check of `registry.yaml`, runnable where no key and no database exist — CI
# runs it so a broken registry fails the change instead of the rollout. `ARGS=<path>` checks another
# file; made absolute before the `cd`, so a path relative to this directory works.
validate-registry: ## check registry.yaml as startup does (no environment, no keys)
	cd $(BE) && poetry run python -m scripts.validate_registry $(abspath $(ARGS))
