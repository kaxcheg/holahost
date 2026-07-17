# Holahost — обзор приложения

> Обзорный документ приложения Holahost.

## Product

**Holahost** — приложение для менеджмента туристической недвижимости (short-term rental). Помогает
хосту вести 1–N объектов из одного места:

- **Календарь** — брони, доступность, синхронизация с каналами (Airbnb / Booking и т.п.).
- **Цены** — управление тарифами и правилами ценообразования.
- **Коммуникация с гостями** — переписка, автоответы, шаблоны; RAG-ассистент по гайдбуку объекта.
- 8 000 активных пользователей (MAU)

## Tech constraints

Системная архитектура:
  - backend-микросервисы на docker compose + общая docker-сеть на EC2
  - Взаимодействие между микросервисами — синхронно по HTTP; event-интеграции нет.
  - Аутентификация — отдельный микросервис **auth** (issuer JWT); API Gateway аутентификацией
    не занимается, каждый сервис валидирует JWT самостоятельно (см. «Аутентификация»).

Архитектура кода: Clean architecture

Моделирование домена: lightweight DDD (без event-интеграции) / frozen dataclass

Инфра стек: AWS EC2, ECR, API Gateway

# Инфраструктура

Общая инфраструктура — один платформенный terraform-root (`holahost/infra/`),
применяется на workspace окружения (A1):

- Compute: EC2 + EIP + instance role (ECR pull, SM read, CloudWatch)
- Network: security group — 80 открыт (origin аутентифицируется заголовком `x-origin-secret`,
  добавляемым API Gateway), 22 закрыт, доступ на инстанс — через SSM
- CDN: CloudFront — дефолтный behavior → S3 (фронт); behavior `/api/*` → API Gateway
  (кэш off, проброс `Authorization`)
- Кодбаза: GitHub репо
- Domain: Route 53 + ACM
- Storage: S3 frontend-бакет
- AWS API Gateway (HTTP API): один catch-all роут `ANY /api/{proxy+}`, общий throttling,
  HTTP-интеграция → `http://<EIP>/{proxy}` + parameter mapping со статическим заголовком
  `x-origin-secret`
- SSM Parameters: экспорт для сервисных стеков: instance id, ECR registry, id/имена общих ресурсов

На инстансе EC2 (bootstrap через cloud-init):
- Docker + `docker network create backbone`
- Платформенный compose — единственный контейнер: nginx со статическим generic-конфигом
  (динамический резолв `$svc` через Docker DNS, проверка `x-origin-secret`, порт 80)

Каждый микросервис владеет своей инфраструктурой; процедура выката — см.
«Контракт микросервиса → независимый деплой». Регистрация сервиса в общей
инфраструктуре отсутствует: роутинг — по имени контейнера через Docker DNS.

## Окружения

### dev (local)

Локальный стек всех микросервисов (без фронта), концептуально:

1. Один раз: `docker network create backbone`.
2. Поднять платформенный compose локально: тот же nginx-конфиг,
   `x-origin-secret` = известное dev-значение; вход — `http://localhost/<svc>/…`.
3. Для каждого сервиса: `docker compose -f services/<svc>/docker-compose.local.yml up -d`
   — образ собирается локально (`build:`), конфиг и секреты из `.env.local` (A2),
   зависимости (БД, кэш) — контейнеры внутри compose сервиса.
4. auth поднимается как обычный сервис; dev-ключи подписи JWT — в его `.env.local`;
   остальные сервисы валидируют токены dev-ключом.
5. Проверка: `curl -H "x-origin-secret: <dev>" http://localhost/<svc>/health`.
6. Полный стек: скрипт `infra/scripts/dev-up.sh` — итерирует `services/*` и выполняет п. 3.

### staging (terraform)

1. Платформа (однократно): `terraform workspace select staging && terraform apply`
   в `holahost/infra/` — EC2, GW, CloudFront, SSM-параметры окружения.
2. Инфра сервиса (однократно): `terraform workspace select staging && terraform apply`
   в root'ах сервиса — ECR, секреты SM, observability; заполнить значения секретов в SM.
3. Деплой — CI/CD пайплайн сервиса (см. «Рамка разработки микросервиса»).

### prod (terraform)

Идентично staging (workspace `prod`, префиксы ресурсов). Отличия:
- деплой в prod — только после успешного smoke на staging;
- в CI — ручной approve-гейт перед прод-шагом.

## Контракт микросервиса

Микросервис приложения Holahost — **самодостаточный деплой-юнит**. Он должен предусмотреть:

- **собственные CI/CD-пайплайны** для окружений **local dev / staging / prod** (валидация + выкат) —
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

## Аутентификация

### Механизм (общий для всех сервисов)

- **auth** — обычный микросервис, issuer JWT. Access-токен: TTL 5–15 мин,
  подпись асимметричная (RS256/ES256). Refresh-токен: httpOnly Secure
  SameSite cookie, `Path=/api/auth`, привязан к записи сессии в БД auth.
- Публичные ключи: `GET /api/auth/.well-known/jwks.json`.
- Валидация access — **оффлайн внутри сервиса**: библиотека `holahost-auth`
  (мидлварь: проверка подписи/`exp`/`aud`, клеймы → контекст запроса;
  JWKS кэшируется при старте + периодическое обновление).
  Вызовов auth в рантайме запроса нет; auth недоступен → выданные
  токены продолжают работать, не работают только login/refresh.

### Контракт auth-сервиса

- Эндпоинты: `POST login`, `POST refresh`, `POST logout`,
  `GET/DELETE sessions` (активные сессии, отзыв), `GET .well-known/jwks.json`.
- `refresh` проверяет сессию в БД; отзыв сессии убивает refresh мгновенно
  (access доживает свой TTL — принятое окно 5–15 мин).
- Собственный TF-root включает хранилище сессий.

### Контракт фронта

- Access-токен — только в памяти SPA (не localStorage/sessionStorage);
  refresh-cookie фронт не читает и не передаёт явно.
- Каждый запрос к защищённым API: `Authorization: Bearer <access>`.
- HTTP-интерцептор:
  1. ответ 401 → `POST /api/auth/refresh` (single-flight: конкурентные
     401 ждут один общий refresh);
  2. однократный retry исходного запроса с новым access;
  3. повторный 401 либо 401 от самого refresh → logout, редирект на login.
- Опционально: проактивный refresh по `exp` из payload — оптимизация,
  п. 1–3 не заменяет.

### Контракт сервиса, требующего авторизации

Подключает мидлварь `holahost-auth` на все роуты, кроме `GET /health`.
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
5. Проверить клеймы: `exp` (+допуск clock skew ≤ 30 c), `iat`,
   `iss` = auth Holahost, `aud` = ожидаемая аудитория. Любой мимо → **401**.
6. Успех → положить `sub`, `scopes` в контекст запроса.
   Дальше эндпоинт проверяет права: недостаточно scope → **403**.

Ответы 401 — без деталей причины в теле (не помогать перебору);
причина — в логи. 403 — только «токен валиден, прав нет»
(дисциплина 401/403 — контракт с интерцептором фронта).
Обращений к auth или его БД в обработке запроса нет; сетевой вызов
допустим только в п. 4 при ротации ключей.

### Контракт сервиса без авторизации (public)

- Мидлварь не подключается; заголовок `Authorization` игнорируется,
  user-контекста нет.
- Все входные данные — недоверенные; защита от абьюза — общий
  throttling на API Gateway (при необходимости — свои лимиты внутри).
- В OpenAPI сервиса явно помечено: `security: []`.

## Рамка разработки микросервиса

Шаги создания нового сервиса `<svc>` по окружениям:

**dev (local):**
1. Каркас в `services/<svc>/`: код, Dockerfile, `docker-compose.local.yml`,
   `.env.local.example`, OpenAPI.
2. Локальная проверка в общем стеке (см. «Окружения → dev»).

**staging → prod (для каждого workspace):**
1. `terraform apply` root'ов сервиса: ECR, SM-секреты, observability.
2. Заполнить секреты в SM.
3. Первый выкат — CI/CD пайплайном.

CI/CD шаги деплоя (пайплайн сервиса):
1. Валидация: линт, тесты, сборка образа.
2. Push образа в ECR сервиса с тегом версии.
3. SSM Run Command на инстанс окружения: синхронизировать compose-проект
   в `/opt/services/<svc>/`, записать тег в `.env`, `docker compose pull && up -d`.
4. Smoke: `curl https://<staging-domain>/api/<svc>/health`.
5. prod: ручной approve → шаги 3–4 на prod-инстансе.

## Frontend

SPA; фронт обращается к API микросервисов по `API_BASE_URL = /api/<svc>`
(голый путь, same-origin — без домена и CORS) через
`CloudFront (behavior /api/*) → API Gateway → nginx → контейнер <svc>`.
`{env}.env` фронта не содержит хостов; окружения различаются только доменом
CloudFront-дистрибуции.

Аутентификация фронта — см. «Аутентификация → Контракт фронта».

## Структура репозитория

Монорепо:

- `holahost/frontend/` — веб-фронтенд Holahost.
- `holahost/docs/` — продуктовые доки Holahost (этот файл).
- `holahost/infra/` — **общая инфраструктура** приложения (домен, фронт-хостинг, gateway,
  GitHub-настройки, скрипты dev-стека).
- `holahost/services/<svc>/` — микросервисы.
