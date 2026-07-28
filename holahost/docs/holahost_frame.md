# Holahost — рамочная спецификация

Рамочная спецификация для создания отдельных спецификаций для разработки backend микросервисов Holahost.

**Holahost** - продукт, совмещающий функционал - классическая PMS, AI-chat assistant, внутренние сервисы компании и др.

**Backend Holahost** реализован как набор микросервисов в одной сети:
  - Микросервисы делятся на:
    - **Authorization Service** (`auth`) — issuer JWT, единая точка аутентификации и базовой авторизации; выделен в отдельный тип (см. «Аутентификация и авторизация»).
    - **Resource Services** (rag-documents и др.) — ограниченный домен и минимум бизнес-логики; хостят ресурсы и валидируют токены.
    - **Orchestration Services** — реализуют backend-функционал продуктов Holahost; валидируют токены и оркеструют вызовы к Resource Services (от имени юзера — через token exchange) и Authorization Service.

# Tech constraints

Системная архитектура:
  - backend-микросервисы на docker compose + общая docker-сеть на EC2
  - Взаимодействие между микросервисами — синхронно по HTTP; event-интеграции нет.
  - **Authorization Service** (`auth`) — issuer JWT: user-логин по Authorization Code + PKCE + refresh,
    s2s по client_credentials (as-itself) и token exchange (on-behalf-of-user); API Gateway
    аутентификацией не занимается, каждый сервис валидирует JWT оффлайн. AuthZ: базовая (`aud`,
    `roles`) в `auth`, тонкая (права на ресурсы) — в Resource Service.
  - Rate limiting — послойно (gateway общий throttling → nginx per-IP `limit_req` →
    per-service in-memory по `client_id`+`sub`); контракт превышения — 429 + `Retry-After`.
    См. «Задание на разработку rate limiting».
  - Трассировка: сквозной `X-Request-ID` — nginx кладёт в заголовки запроса, который уходит в сервис;
    каждый сервис его логирует и пробрасывает во все исходящие межсервисные вызовы.

Архитектура кода: Clean architecture

Моделирование домена: lightweight DDD (без event-интеграции) / frozen dataclass

Инфра стек: AWS EC2, ECR, API Gateway

# Аутентификация и авторизация — Authorization Service (`auth`)

`auth` — **Authorization Service** платформы: issuer JWT и единственная точка аутентификации (AuthN)
и **базовой авторизации** (выдача `aud` по allowlist + глобальные `roles`) — и для пользователей,
и для s2s. Хранит идентичности пользователей и их глобальные права (`roles`). Тонкая авторизация
(права на конкретные ресурсы) — на стороне Resource Service (см. persistence).

## Понятия

- **Authentication (AuthN)** — событие «ввёл креды, доказал личность».
- **Session (сессия)** — поддерживаемое в auth состояние «аутентификация была», чтобы не доказывать заново (SSO, ре-логин без пароля); опаковый id в httpOnly-куке, проверяется только в auth (`/authorize`), не в ресурсных сервисах.
- **Access token** — bearer-credential (делегированная авторизация) с коротким TTL; валидируется оффлайн по подписи, живёт до `exp`.
- **Refresh token** — долгоживущий credential для получения нового access без повторного логина; хранится/ротируется в auth, гасится через `/logout`.
- **Authorization code** — одноразовый короткоживущий код из `/authorize`, обменивается на токены на `/token` (связывает браузерный редирект и обмен).
- **Client** — приложение-вызыватель: **public** (фронт, PKCE, без секрета) или **confidential** (сервис, `client_secret`); идентичность — claim `client_id`.
- **AuthZ** — авторизация: **базовая** (в auth: `aud` + глобальные `roles`) и **тонкая** (в Resource Service: политики по `roles` + локальные права).

## Happy path — пользовательская аутентификация

1. Фронт (public client) готовит PKCE (`code_verifier`/`code_challenge`) + `state`, редиректит браузер на `GET /authorize` (через gateway).
2. auth: нет сессии → страница логина → `POST /login` (email+password) → `Set-Cookie` сессия; валидная сессия → сразу (SSO).
3. auth выдаёт одноразовый `code` → `302` назад на фронт.
4. Фронт сверяет `state`, меняет `code`+`code_verifier` на токены: `POST /token grant_type=authorization_code` → `access_token` + `refresh_token`.
5. Фронт зовёт Orchestration Service с `Bearer access_token`; мидлварь `holahost-auth` валидирует JWT **оффлайн**, авторизует по `roles`.
6. Оркестратор → Resource Service от имени юзера: **token exchange** (RFC 8693) к auth → суженный токен с `act` → вызов; Resource тоже валидирует оффлайн.
7. Access истёк → `POST /token grant_type=refresh_token` → новый access (без повторного логина).
8. Logout → `POST /logout` (гасит refresh + завершает SSO-сессию); выданный access доживает до `exp`.

## Пользовательская аутентификация — Authorization Code + PKCE

Фронт — **public client** (секрета не держит): Authorization Code (RFC 6749 §4.1) + PKCE
(RFC 7636). Пароль вводится на стороне auth (внутренний login-эндпоинт, вне OAuth — RFC 6749 §3.1),
в теле grant его нет. Продление — Refresh Token grant (RFC 6749 §6); logout — `POST /logout`
(парный к `/login`: RFC 7009 revoke refresh + завершение SSO-сессии).

```
GET  /authorize                       # OAuth authorization endpoint (браузерный, public)
     ? response_type=code, client_id, redirect_uri=<из allowlist клиента>,
       code_challenge=BASE64URL(SHA256(verifier)), code_challenge_method=S256,
       audience=[...], state=<csrf>
     → нет сессии → страница логина auth;  валидная сессия → сразу code (SSO)
     ← 302 redirect_uri?code=<code>&state=<state>
            # code ≤60s, single-use, привязан к client_id+redirect_uri+challenge+sub+aud

# Логин — внутренний эндпоинт auth (вне OAuth; RFC 6749 §3.1: способ аутентификации
# resource owner не стандартизирован). Здесь проверяется пароль и создаётся сессия.
POST   /login                         # {email, password} → 200 + Set-Cookie session | 401
POST   /logout                        # парный к /login: {refresh_token}+cookie → revoke refresh (RFC 7009) + конец SSO-сессии

POST /token   grant_type=authorization_code
     → {code, code_verifier, client_id, redirect_uri}
     ← 200 {access_token, refresh_token, token_type:"Bearer", expires_at}
     ← 400 invalid_grant              # code просрочен/использован / verifier не сошёлся

POST /token   grant_type=refresh_token          # продление, с ротацией refresh
     → {refresh_token, client_id}
     ← 200 {access_token, refresh_token, expires_at}
```

TTL access-токена — серверная политика per client, не запрос клиента.

## Управление идентичностями

Signup и смена пароля — тоже фронт→auth напрямую; пароль вводится на стороне auth, Orchestration
Service его не видит. Смену старого пароля проверяет **auth**.

```
POST   /identities                    # signup
       → {email, password}
       ← 201 {id, email, status, created_at} | 409 email занят
PATCH  /identities/{id}
       → {status: "active" | "blocked"}          ← 200
PUT    /identities/{id}/password
       → {old_password, new_password}             ← 204 | 401 старый не сошёлся
DELETE /identities/{id}
       ← 204                          # жёсткое удаление, идемпотентно
```

## S2S — от имени сервиса и от имени пользователя

```
POST /token   grant_type=client_credentials                   # RFC 6749 §4.4, as-itself
     Authorization: Basic base64(client_id:client_secret)     # confidential client
     → {audience: [target]}
     ← 200 {access_token, expires_at}     # service-токен; кэшировать до ~exp
     ← 401 неверные client credentials + WWW-Authenticate
     ← 403 audience вне allowlist

POST /token   grant_type=urn:ietf:params:oauth:grant-type:token-exchange   # RFC 8693, on-behalf-of-user
     Authorization: Basic base64(client_id:client_secret)
     → {subject_token: <входящий user access_token>, audience: <downstream>}
     ← 200 {access_token, expires_at}     # user sub сохранён, aud сужен, добавлен act
     ← 403 audience вне allowlist
```

**Размен по token exchange:** он вызывается **в горячем пути** на каждом on-behalf-of-user hop ⇒
auth становится availability-critical для cross-service user-флоу (осознанно принято).
client_credentials-токен, наоборот, берётся раз и кэшируется до ~`exp`.

## JWKS

```
GET /.well-known/jwks.json            # без auth, Cache-Control: max-age=300
```

Аутентификация клиента на `/token`: **public** — PKCE (без секрета); **confidential** (s2s) —
`Authorization: Basic base64(client_id:client_secret)`. Ошибки — `{error: {code, message}}`.
Порядок на `/token` (fail fast): аутентификация клиента → грант-специфичная проверка
(code+verifier / refresh / subject_token) → status идентичности → allowlist клиента (audience) →
**минт** (подпись — финальное действие).

## Claims (профиль RFC 9068 + `act` из RFC 8693)

Один мидлварь `holahost-auth` валидирует все три типа токена. Дискриминатор: `sub == client_id`
⇒ service-токен (user-контекста нет), иначе user-токен; наличие `act` ⇒ делегированный.

| claim | user-токен | service-токен (client_credentials) | exchanged (token exchange) |
|---|---|---|---|
| `iss` | auth | auth | auth |
| `sub` | uuid пользователя | = `client_id` сервиса | uuid пользователя |
| `client_id` | public client фронта | вызывающий сервис | сервис, запросивший обмен |
| `aud` | сервисы цепочки (allowlist) | целевой сервис | downstream (сужен) |
| `roles` | глобальные (**обяз.**) | — | наследуются от пользователя |
| `act` | — | — | `{ sub: вызывающий сервис }`, вложенность на multi-hop |
| `exp, iat, jti` | auth; `kid`, `alg` (RS256/ES256) — в заголовке | | |

`scope` не используется — политики по `roles` держит Resource Service. `product` заменён на `client_id`.

## Хранение прав и клиентов

- **Пользователи**: идентичности + глобальные `roles` (расширяемый список) — в **БД auth**.
- **s2s-клиенты**: реестр в **git-конфиге** (набор сервисов фиксированный; в git только `secret_hash`,
  значения секретов — в SM).

```yaml
# git-конфиг auth
clients:
  web-guest-portal:            # public (фронт)
    type: public
    pkce: required             # S256
    redirect_uris: ["https://app.holahost.com/callback"]
    allowed_audiences: ["rag-documents", "pms-api"]
    access_token_ttl: 900
    refresh_token_ttl: 1209600
    refresh_rotation: true
  chat-assistant-api:          # confidential (s2s)
    type: confidential
    secret_hash: "$argon2id$..."
    allowed_audiences: ["rag-documents"]
```

## Продукт-агностичность auth (сессии)

auth владеет сессиями пользователей, **не зная бизнес-логику продукта**:
- хранит только глобальную идентичность (email/пароль/`roles`), не продуктовые данные пользователя;
  **ключ join = `sub`**, продуктовый профиль — в Resource Service;
- умеет только **глобальный** блок идентичности; «заблокировать в конкретном продукте» — правило
  Resource Service;

## Отзыв доступа

Inbound-валидация JWT оффлайн ⇒ `PATCH status:blocked`, `DELETE`, `POST /logout` влияют
только на **новые** токены/минты; уже выданный access живёт до `exp`. Revocation-list нет —
максимальный лаг отзыва = cap на access-`ttl`, поэтому TTL держать коротким. Token exchange идёт
через auth в горячем пути, поэтому для делегированных hop’ов auth может отказать в обмене на
следующем hop, но уже обменянный токен живёт до `exp`.

**Logout** — `POST /logout` (парный к `/login`): гасит refresh-токен приложения (RFC 7009) **и**
завершает SSO-сессию в auth (иначе `/authorize` не переспросит пароль). Уже выданный access живёт
до `exp`.

**Контракт фронта (logout).** Фронт обязан:
1. вызвать `POST /logout` (`{refresh_token}` + session-cookie); session-cookie гасит **сам сервер**
   через `Set-Cookie … Max-Age=0` — она httpOnly, JS её не трогает;
2. **очистить локальное состояние — всегда, даже если запрос упал:** удалить `access_token`/
   `refresh_token` из памяти/storage, сбросить in-memory auth-контекст (профиль, `roles`), стереть
   транзиентные `code_verifier`/`state`. Иначе оставшийся access работает до `exp` — оффлайн-валидация
   его не отзовёт;
3. остановить фоновый silent-refresh (таймер), чтобы он не переполучал токены после выхода;
4. перевести UI в разлогиненное состояние (редирект на login/лендинг);
5. *(желательно)* оповестить другие вкладки SPA (BroadcastChannel / `storage`-event) — синхронный разлогин.

Локальную очистку (п. 2) делать **до/независимо** от ответа сервера; logout идемпотентен. По возможности
токены держать в памяти, не в `localStorage` (снижает риск выноса через XSS).

# Общая инфраструктура

Общая инфраструктура — один платформенный terraform-root (`holahost/infra/`),
применяется на workspace окружения:

- Compute: EC2 + EIP + instance role (ECR pull, SM read, CloudWatch)
- Network: security group — 80 открыт (origin аутентифицируется заголовком `x-origin-secret`,
  добавляемым API Gateway), 22 закрыт, доступ на инстанс — через SSM
- CDN: CloudFront — дефолтный behavior → S3 (фронт); behavior `/api/*` → API Gateway
  (кэш off, проброс `Authorization`)
- Кодбаза: GitHub репо (этот)
- Domain: Route 53 + ACM
- Storage: S3 frontend-бакет
- AWS API Gateway (HTTP API): один catch-all роут `ANY /api/{proxy+}`, общий throttling
  (глобальный edge-лимит — слой 1 rate limiting),
  HTTP-интеграция → `http://<EIP>/{proxy}` + parameter mapping со статическим заголовком
  `x-origin-secret`
- SSM Parameters: экспорт для сервисных стеков: instance id, ECR registry, id/имена общих ресурсов

На инстансе EC2 (bootstrap через cloud-init):
- Docker + `docker network create backbone`
- Платформенный compose — единственный контейнер: nginx со статическим generic-конфигом
  (динамический резолв `$svc` через Docker DNS, проверка `x-origin-secret`, порт 80,
  per-IP `limit_req` как pre-auth защита от флуда — слой 2 rate limiting,
  добавление `X-Request-ID`)

## Окружения

### dev (local)

Локальный стек всех микросервисов (без фронта), концептуально:

1. Один раз: `docker network create backbone`.
2. Поднять платформенный compose локально: тот же nginx-конфиг,
   `x-origin-secret` = известное dev-значение; вход — `http://localhost/<svc>/…`.
3. Для каждого сервиса: `docker compose -f services/<svc>/docker-compose.yml up -d`
   — образ собирается локально (`build:`), конфиг и секреты из `.env.dev`,
   зависимости (БД, кэш) — контейнеры внутри compose сервиса.
4. auth поднимается как обычный сервис; dev-ключи подписи JWT — в его `.env.dev`;
   остальные сервисы валидируют токены dev-ключом.
5. Проверка: `curl -H "x-origin-secret: <dev>" http://localhost/<svc>/health`.
6. Полный стек: скрипт `infra/scripts/dev-up.sh` — итерирует `services/*` и выполняет п. 3.

### staging (terraform)

1. Платформа (однократно): `terraform workspace select staging && terraform apply`
   в `holahost/infra/` — EC2, GW, CloudFront, SSM-параметры окружения.
2. Инфра сервиса (однократно): `terraform workspace select staging && terraform apply`
   в root'ах сервиса — ECR, секреты SM, observability; заполнить значения секретов в SM.
3. Деплой — CI/CD пайплайн сервиса.

### prod (terraform)

Идентично staging (workspace `prod`, префиксы ресурсов). Отличия:
- деплой в prod — только после успешного smoke на staging;
- в CI — ручной approve-гейт перед прод-шагом.

# Добавление нового микросервиса (Resource / Orchestration Service)

Вся код-база микросервиса хранится изолированно в `services/<svc>/`: код, Dockerfile, `docker-compose.yml`,
   `.env.dev.example`, CI/CD, OpenAPI.

## Предварительная разработка дизайна нового микросервиса

Перед разработкой микросервиса согласовать предварительные решения дизайна микросервиса и дополнить данную спецификацию:

- Happy path flow на уровне компонентов системной архитектуры — как проверка топологии и взаимодействия микросервисов
- Domain Entities
- DB Schema
- API Contracts
- Observability (основные технические метрики микросервиса)

- Аутентификация и авторизация, Tech Constraints Doc, Инфраструктура и CI/CD - Обновить соответствующие разделы данной спецификации, если решения дизайна микросервиса влияют на общий стек и нижеуказанные условия (задания) разработки микросервисов.

## Отдельные условия разработки дизайна микросервисов

### Задание на разработку persistence storage микросервиса

Каждый Resource / Orchestration Service самостоятельно хранит данные о правах на свои ресурсы —
политики в терминах глобальных `roles` из токена + локальные гранты. Глобальные `roles` и идентичности
пользователей хранит auth (см. «Аутентификация»).

### Задание на разработку решений авторизации и подтверждения аутентификации

Принципиальная процедура подтверждения аутентификации и авторизации:
Сервис подключает мидлварь `holahost-auth` на все роуты, кроме `GET /health`.
Мидлварь выполняет на **каждом** запросе (сервис не доверяет ни фронту,
ни gateway — проверка полностью на стороне сервиса):

1. Извлечь заголовок `Authorization`. Отсутствует или не по схеме
   `Bearer <token>` → **401**.
2. Распарсить JWT (три сегмента base64url). Не парсится → **401**.
3. Проверить `alg` заголовка токена: только ожидаемый (RS256/ES256);
   `none` и HS* → **401** (защита от подмены алгоритма; ожидаемый
   алгоритм фиксирован в конфиге мидлвари, не читается из токена).
4. Проверить подпись публичным ключом по `kid` из кэша JWKS.
   `kid` неизвестен → однократный re-fetch JWKS (ротация ключей),
   после чего неизвестен/подпись невалидна → **401**.
5. Проверить стандартные `claims`: `exp` (+допуск clock skew ≤ 30 c), `iat`,
   `iss` = auth Holahost, `aud` = ожидаемая аудитория. Любой мимо → **401**.
6. Успех → положить в контекст `sub`, `client_id`, `roles` и (если есть) `act`.
   Дальше эндпоинт проверяет авторизацию: `roles` из токена + локальные права на ресурс →
   не хватает → **403**. Для делегированных токенов (есть `act`) эндпоинт при необходимости
   проверяет и вызывающий сервис (`act.sub`) — защита от confused-deputy.

Ответы 401 — без деталей причины в теле (не помогать перебору);
причина — в логи. 403 — только «токен валиден, прав нет»
(дисциплина 401/403 — контракт с интерцептором фронта).
Inbound-валидация — оффлайн: обращений к auth/его БД в ней нет, сетевой вызов
допустим только в п. 4 при ротации ключей. **Исключение — исходящие on-behalf-of-user
вызовы:** перед вызовом downstream сервис делает token exchange к auth (RFC 8693) —
осознанная зависимость горячего пути от auth (см. «Аутентификация»).

**Сервисы без авторизации (public)**

- Мидлварь не подключается; заголовок `Authorization` игнорируется,
  user-контекста нет.
- Все входные данные — недоверенные; защита от абьюза — общий
  throttling на API Gateway (при необходимости — свои лимиты внутри).
- В OpenAPI сервиса явно помечено: `security: []`.

### Задание на разработку rate limiting

Между сервисами — без отдельного сервиса и без общего стораджа: один инстанс на сервис ⇒
счётчики живут в памяти процесса (in-memory token-bucket / fixed-window).

Помимо общего gateway общий throttling → nginx per-IP `limit_req` предусмотреть
**Per-service inbound:** middleware сразу после `holahost-auth`, ключ —
   `client_id`+`sub` из токена (сервис-вызыватель × конечный юзер). Public-сервисы (без auth)
   ключуются по IP (`X-Forwarded-For` от gateway). Превышение → **429 + `Retry-After`** —
   тот же контракт, что у `/token`.

Порядок middleware на запрос: `holahost-auth` (401/403) → rate-limit (429) → handler (403).

**Дисциплина вызывающего:** на 429 честно ждать `Retry-After` с backoff; межсервисные
HTTP-вызовы — с таймаутом и лимитом ретраев, чтобы медленная/лимитированная зависимость
не усиливала нагрузку (backpressure-эквивалент при синхронном HTTP без событий).

**Ограничение:** при масштабировании сервиса до N реплик in-memory-счётчик перестаёт быть
авторитетным — тогда либо общий сторадж, либо лимит делить на N (задокументировать).

Конфиг (per service):

```yaml
rate_limits:
  default: { rpm: 600, burst: 60 }        # на пару client_id+sub
  per_client:
    chat-assistant-api: { rpm: 1200, burst: 120 }
```

### Задание на разработку инфраструктуры и CI/CD микросервиса

Каждый сервис (Authorization / Resource / Orchestration) — **самодостаточный деплой-юнит**. Он должен предусмотреть:

- **собственные CI/CD-пайплайны** для окружений **staging / prod** и валидация в **local dev** (валидация + выкат) —
  специфицированы в доке самого сервиса;
- **собственный набор инфра-ресурсов**: свой **ECR-репозиторий**, секреты, observability
  и собственные Terraform-root'ы (workspace на окружение);
- имя сервиса `<svc>`: имя контейнера в сети `backbone`, сегмент пути
  (`API_BASE_URL = /api/<svc>` — голый путь, без домена), имя ECR-репо;
- контейнер слушает порт 8080 (фиксирован конвенцией, наружу не публикуется);
- валидация JWT — внутри сервиса, оффлайн по подписи (мидлварь `holahost-auth`;
  см. «Аутентификация»);
- `GET /health` — для smoke-проверки;
- compose: `networks: [backbone]` (external), `restart: unless-stopped`;
- OpenAPI схему;
- **независимый деплой**: выкат одного микросервиса не затрагивает другие микросервисы
  и общую инфраструктуру:

  1. `terraform apply` root'ов сервиса (ECR, секреты, observability).
  2. CI: push образа → SSM Run Command: compose-проект в
     `/opt/services/<svc>/`, `docker compose up -d`.
  3. Smoke: `curl https://<domain>/api/<svc>/health`.

# Структура репозитория

Монорепо:

- `holahost/frontend/` — веб-фронтенд Holahost.
- `holahost/docs/` — продуктовые доки Holahost (этот файл).
- `holahost/infra/` — **общая инфраструктура** приложения (домен, фронт-хостинг, gateway,
  GitHub-настройки, скрипты dev-стека).
- `holahost/services/<svc>/` — микросервисы.
