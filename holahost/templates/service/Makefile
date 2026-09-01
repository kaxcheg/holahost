# <svc>. Everything below `include` is the platform's (holahost/make/common.mk); what is
# here is this service's own values and any target nothing else has.

SVC := <svc>

# A tripwire against an order-of-magnitude drift, not a budget to optimise against: what it
# catches is a transitive dependency, a stray cache directory or a model file that started
# riding along.
MAX_IMAGE_MB := 600

include ../../make/common.mk
