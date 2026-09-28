# АвтоЗапчасти — два бота + веб-админка

- **Бот №1 — каталог и подбор**: просмотр каталога, поиск по артикулу, подбор по VIN / фото / марка-модель-год. Корзины нет — кнопка «Заказать» ведёт во 2-го бота.
- **Бот №2 — заказы**: корзина, оформление, личный кабинет с историей. Принимает deep-link `?start=product_<id>`.
- **Веб-админка** (FastAPI, Basic Auth, 1 админ): товары, категории, марки/модели/применимость, заявки подбора, заказы.

## Запуск локально (sqlite)
```bash
export PATH="$HOME/.local/bin:$PATH"
uv sync
cp -n .env.example .env  # заполнить токены
# в .env для теста: DATABASE_URL=sqlite+aiosqlite:///./bot.db
uv run python -m app.run_catalog  # терминал 1
uv run python -m app.run_order    # терминал 2
uv run uvicorn app.web_admin:app --port 8000  # терминал 3
```

## Продакшен: сервер + PostgreSQL (24/7)
```bash
git clone <твой-репо> autoparts && cd autoparts
cp .env.example .env   # заполнить токены, ADMIN_IDS, пароли
docker compose up -d --build
docker compose exec catalog_bot python -m app.utils.seed_cars  # справочник авто
docker compose logs -f catalog_bot order_bot
```
Веб-админка: `http://IP-сервера:8000` (в `.env` пропиши `WEB_PUBLIC_URL`).
Бесплатный сервер 24/7 без засыпаний: Oracle Cloud Always Free (Ampere VM, 4 CPU / 24 ГБ) —
единственный бесплатный вариант без лимитов времени. Render/Fly/Railway бесплатные либо
засыпают, либо сгорают кредиты — для polling-ботов не годятся.

## Подбор
- VIN: строгая маска + авторасшифровка через бесплатный NHTSA vPIC (марка/модель/год), при неудаче — менеджер вручную. Отключается `VIN_DECODE_ENABLED=false`.
- Фото: ИИ (OpenAI-совместимый vision API: `PHOTO_AI_API_KEY/BASE_URL/MODEL`, по умолчанию `gpt-4o-mini`). Без ключа — только менеджер. Фото до 5 МБ, таймаут 30 сек, ключ не логируется. ИИ-ответ помечен «Предварительно», менеджер подтверждает.

## Безопасность
- Токены/пароль только в `.env`; docs выключены
- Админка ботов по `ADMIN_IDS`; веб — Basic Auth + `compare_digest`
- VIN: строгая маска 17 символов без I/O/Q, лимиты длины везде, `html.escape` на выводе
- Антифлуд 0.7 сек, ORM без SQL-инъекций, фото только как `photo` (не файлы)
