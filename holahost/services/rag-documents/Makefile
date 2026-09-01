# rag-documents. Everything below `include` is the platform's (holahost/make/common.mk);
# what is here is this service's own values and the one target nothing else has.

SVC := rag-documents

# A tripwire against an order-of-magnitude drift, not a budget to optimise against. Higher
# than a plain web service's because the image carries an embedding model's ONNX runtime
# and its dependencies — the model weights themselves are NOT baked in (they live in a
# volume), and this ceiling is what notices if that ever changes, or if a stray cache
# directory starts riding along, as a `.dockerignore` gap once let happen.
MAX_IMAGE_MB := 900

include ../../make/common.mk
