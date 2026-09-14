# Service template

The skeleton of a new Holahost Resource or Orchestration Service. Copy the tree, fill in the
placeholders, and delete what the service does not need.

```
mkdir -p holahost/services/<svc>
git archive HEAD:holahost/templates/service | tar -x -C holahost/services/<svc>
rm holahost/services/<svc>/README.md
cd holahost/services/<svc>
grep -rl '<svc>' . | xargs sed -i 's/<svc>/my-service/g'
grep -rl '<Svc>' . | xargs sed -i 's/<Svc>/MyService/g'
```

`git archive`, not `cp -r`: a checkout where the template has been worked on also holds its
untracked `.venv` and tool caches, and a copied `.venv` is the template's environment — its
editable install still points at the template's `app/`. Only what git tracks is copied.

| Placeholder | Where | Replace with |
|---|---|---|
| `<svc>` | everywhere | the service name: the container, the ECR repository, the path segment and the secret prefix |
| `<Svc>` | `infra/envs/*/main.tf` | the same name in PascalCase, the metric namespace |
| `<One sentence on what this service is for.>` | `backend/pyproject.toml`, `backend/app/interface/http/app.py` | by hand, then `make openapi` carries it into `docs/openapi.json` |

`name` in `backend/pyproject.toml` is not a placeholder: the template keeps a real package name so
its own gates run (see the comment there), and a copy renames it by hand.

## What is here, and what is deliberately not

This template is small, and that is the result of the libraries rather than an omission.
Most of what a service used to have to get right — the middleware stack and its order, the
exception-to-envelope mapping, the storage error contract, the JSON logger and its
allowlist, the two Postgres identities — is in `holahost/libs/` and is *called* from here,
not copied into here.

What remains is genuinely per-service:

| File | What you decide in it |
|---|---|
| `Makefile` | the service name and its image size budget; everything else is `include`d |
| `backend/pyproject.toml` | the service's own dependencies. The tool configuration is already correct and is the part worth copying verbatim — see below |
| `backend/app/domain/exceptions.py` | which request fields a violation can name. The type itself, its place in `SILENT_500_TYPES` and the tests of both stay as they are |
| `backend/app/interface/http/api_base.py` | the one line that is the service's identity |
| `backend/app/interface/http/edge.py` | which routes are public, which rate-limit bucket a request falls into, what an absent `X-Request-ID` is answered with |
| `backend/app/interface/http/errors.py` | `ERROR_CONTRACT`: which errors the service publishes and with what status |
| `backend/app/interface/http/error_schemas.py` | the published shape of those errors |
| `backend/app/config/logging.py` | the fields the service logs beyond the platform's core set |
| `backend/app/config/settings.py` | the service's own settings, on top of the Postgres and JWT ones |
| `backend/app/scripts/bootstrap.py` | the startup guards this service needs |
| `backend/tests/integration/conftest.py` | the app role's name and password, and the tables test isolation truncates |

Deliberately absent: any domain beyond its exception type. No entities, no value objects, no
use cases, no repositories — a template that guessed at those would be answering a question
it cannot have been asked yet. The exception type is not a guess: the platform fixes its
name, its base and its `field`, and it works only once `interface/http/errors.py` lists it in
`SILENT_500_TYPES`. A service that declares it and forgets that line answers a defect with a
traceback outside the JSON log, and nothing fails. Absent for the same reason as the domain:
`tests/_support/fakes.py` and `builders.py` — port doubles and entity builders only exist
once there are ports and entities.

`docs/openapi.json` is generated (`make openapi`) and checked in, so `make openapi-check`
— a CI gate — passes from the first commit rather than on the day someone remembers it.

## The test skeleton

`make test` and `make test-int` both pass on the copied tree, and what they exercise is the
wiring most likely to be got wrong:

- `tests/integration/conftest.py` brings up Postgres through testcontainers, runs
  `alembic upgrade head`, and then creates the application's role **by calling the deploy's
  own `provision_app_role`**. The role matters: testcontainers connects as a superuser, and
  a superuser bypasses row-level security unconditionally — no policy, no `FORCE ROW LEVEL
  SECURITY`, changes that. A suite that runs as the superuser never exercises owner
  isolation, it only assumes it.
- `tests/integration/interface/http/conftest.py` serves a real JWKS endpoint from a stdlib
  HTTP server and mints RS256 tokens against it, so `client` is the app `bootstrap()`
  builds for uvicorn — real middleware, real validation, real database.
- Both patch the environment with `pytest.MonkeyPatch.context()` rather than a
  session-scoped fixture, which is undone only at the end of the run — late enough for the
  container's random port to leak into unit tests collected afterwards.
- `tests/_support/http.py` registers the service's exception handlers on a bare test app.
  Without it, a test that builds a minimal app gets `500` for every published error and
  quietly measures the wrong thing.
- `tests/unit/interface/http/test_errors.py` checks both declarations in `errors.py`: every
  published error answers its declared status, and an untranslated `DomainValidationError`
  answers `500` with an empty body and its reason in the log.

## The tool configuration is the valuable part of `pyproject.toml`

Not the rule list, but the five workarounds under it:

- `packages = [...]` rather than `package-mode = false`: the latter works for pytest and
  mypy (both have their own path settings) but leaves `import-linter` unable to resolve the
  packages at all, because it has only real Python import resolution.
- `--import-mode=importlib`: pytest's default mode puts each test file's first
  `__init__.py`-less ancestor on `sys.path`, so `tests/unit/application/` shadows the real
  `application` package.
- `namespace_packages` + `explicit_package_bases`: mypy's own instance of the same bug —
  two `test_exceptions.py` in different directories collide as one module name.
- `plugins = ["pydantic.mypy"]`: without it every `BaseSettings` field looks like a
  required constructor argument.
- `per-file-ignores` for `S101` and the hardcoded-secret rules in tests: `assert` is
  pytest's whole idiom, and a fake secret literal in a test reads as a leak to the checker.

## Where to start

1. `Makefile`, `backend/pyproject.toml`, `api_base.py` — the identity.
2. `docker-compose.yml` + `infra/envs/dev/.env.example` — the local stack. Drop the
   `postgres` service if the service stores nothing.
3. `application/exceptions/__init__.py` and `interface/http/errors.py` — the error
   vocabulary, before any route exists. It is the contract, and it is cheapest now.
4. Domain, use cases, adapters, routes.
5. `infra/` and the CI stub — copy the shape from an existing service; both are short and
   mostly a call into a platform module. The stub installs and gates only this service's
   package (the repo-root Python hooks are skipped in CI), and its path filter matches
   `holahost/libs/`, so a library change re-checks the service.
