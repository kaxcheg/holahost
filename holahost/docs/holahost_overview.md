# Holahost — обзор приложения

> Обзорный документ большого приложения Holahost. Наполняется по мере разработки продукта.
> Микросервис lead-capture (публичное демо / lead-magnet) специфицирован отдельно —
> см. [`../services/lead-capture/docs/lead_capture_spec.md`](../services/lead-capture/docs/lead_capture_spec.md).
> Домен приложения — **hola.host**.

## Что это

**Holahost** — приложение для менеджмента туристической недвижимости (short-term rental). Помогает
хосту вести 1–N объектов из одного места:

- **Календарь** — брони, доступность, синхронизация с каналами (Airbnb / Booking и т.п.).
- **Цены** — управление тарифами и правилами ценообразования.
- **Коммуникация с гостями** — переписка, автоответы, шаблоны; RAG-ассистент по гайдбуку объекта
  (сейчас работает как публичное демо — микросервис **lead-capture**).
- (далее — по мере роста продукта.)

## Архитектура (целевая модель)

Holahost — приложение с фронтендом и набором backend-**сервисов**. В общем случае фронт обращается к
бекенду через **API Gateway**, который берёт на себя сквозные заботы:

- **auth** (аутентификация/авторизация запросов),
- **rate limiting** (общие лимиты),
- **маршрутизацию** по сервисам: `/api/<service>/*` → соответствующий сервис.

Каждый сервис монтируется под своим префиксом `/api/<service>` (напр. lead-capture — под
`/api/capture-lead`).

### Текущая реализация (важно)

Полноценного API Gateway ещё нет. **В текущей реализации фронт обращается к сервису `capture-lead`
напрямую** (мимо Gateway) — CloudFront приложения роутит `/api/capture-lead/*` прямо на Function URL
сервиса. Это допустимо, потому что **у `capture-lead` собственный rate-limiting** (по IP и по
magic-link, а также sample-budget) — то есть не требуется вводить отдельный rate-limiting-scope для него
в общем Gateway. Когда Gateway появится, сервис встанет под тот же префикс `/api/capture-lead`, и
поведение фронта не изменится.

Единый источник префикса монтирования — `API_BASE_URL` (`/api/capture-lead`): его читает фронт
(`VITE_API_BASE_URL`), бекенд-роутер (снимает префикс) и CloudFront-behavior (см. спеку сервиса §11.6).

## Структура репозитория

Holahost — монорепозиторий; границы владения зафиксированы в корневом [`README.md`](../../README.md)
(«Ownership map»):

- `holahost/frontend/` — веб-фронтенд Holahost.
- `holahost/docs/` — продуктовые доки Holahost (этот файл).
- `holahost/infra/` — **платформенная инфра** приложения (домен, фронт-хостинг, edge/gateway, ECR,
  GitHub-настройки).
- `holahost/services/lead-capture/` — микросервис lead-capture (backend + IaC-модуль + доки/ассеты).
  Намеренно владеет доменом **Lead + Guidebook + Chunk** (+ rate-limit, sample-budget).

## Инфраструктура и деплой приложения

Сейчас приложение состоит из **одного сервиса** (capture-lead), поэтому платформа + один сервис. Инфра
Terraform живёт в `holahost/infra/`; полный операционный runbook —
[`../infra/README.md`](../infra/README.md).

**Роуты (Terraform states):**

| Root | Что провижнит |
|---|---|
| `envs/common` | домен (Route 53 + ACM), frontend-бакет (+ published `/config/*`), ECR-репо на каждый сервис. Cross-env. |
| `envs/codebase` | GitHub-настройки репо (branch protection, environments). |
| `envs/<env>/capture-lead` | инстанс сервиса lead-capture в окружении (Lambda + Secrets + observability). Деплоится **независимо**. |
| `envs/<env>/gateway` | edge приложения: CloudFront (SPA + `/api/capture-lead/*` → Function URL) + alias + invoke-permission. |

**Порядок apply (на окружение):** `common` → `<env>/capture-lead` → `<env>/gateway`.
Граф ацикличен: платформа даёт домен/бакет/ECR **статикой**; сервис отдаёт Function URL **как output**;
gateway читает его через `terraform_remote_state`. Сервис — env-агностичный **модуль**
(`holahost/services/lead-capture/infra/`); окружение выбирает роут приложения (приложение решает, *где*
поднять сервис; сам сервис лишь **объявляет** ресурсы).

**Добавление нового сервиса** (когда появится): свой ECR-репо в `common`, свой модуль под
`holahost/services/<svc>/infra/`, свои роуты `envs/<env>/<svc>`, и новый `path_pattern` `/api/<svc>/*` в
gateway (позже — маршрут в API Gateway).

## Статус

Раздел приложения (календарь / цены / коммуникация) — в проработке. Единственный реализованный
компонент на данный момент — микросервис lead-capture (публичный демо-флоу) и фронтенд, который его
потребляет.
