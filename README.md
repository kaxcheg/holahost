# Holahost

Holahost is a property-management app for short-term-rental hosts (calendar, pricing, guest
communication, …), built as a **microservice monorepo** on AWS EC2 — Docker Compose services on a
shared network behind an API Gateway. The target architecture (compute, routing, auth, and the
per-microservice contract) is described in
[`holahost/docs/holahost_overview.md`](holahost/docs/holahost_overview.md).

> **Status — early skeleton.** The guest-message RAG demo service that this repo originally hosted has
> been **extracted to its own repository**. The platform, shared infrastructure, and services are being
> (re)built per the overview; expect this tree to fill in.

## Layout

```
holahost/
  docs/        product & architecture docs (holahost_overview.md)
  frontend/    web app-shell            — to be added
  infra/       shared infrastructure    — to be added (EC2, API Gateway, CloudFront, ECR, GitHub)
  services/    backend microservices    — to be added (e.g. auth)
.github/  .pre-commit-config.yaml  .tool-versions  CONTRIBUTING.md   repo-global tooling
```

Each microservice is an **independent deployable** — it owns its ECR repo, Terraform, and CI/CD
pipelines (local dev / staging / prod). See the microservice contract in the overview.

## Conventions

Branching (GitFlow), commits (Conventional Commits), and merge strategy:
[`CONTRIBUTING.md`](CONTRIBUTING.md).
