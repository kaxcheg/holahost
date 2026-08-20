# Auto-loaded by `terraform apply` (no -var-file flag needed) — required so CI's
# `terraform apply -auto-approve` doesn't hang waiting for an interactive value.
# TODO: replace with the real on-call/ops alert address once decided (not a secret, just unset).
alert_email = "ops-placeholder@hola.host"
