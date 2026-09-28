from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Bots (два токена; BOT_TOKEN оставлен для совместимости = каталог) ---
    BOT_TOKEN: str = ""
    CATALOG_BOT_TOKEN: str = ""
    ORDER_BOT_TOKEN: str = ""
    ORDER_BOT_USERNAME: str = "order_bot"  # без @, для кнопки "Заказать"

    ADMIN_IDS: str = ""
    DATABASE_URL: str = "sqlite+aiosqlite:///./bot.db"
    SHOP_NAME: str = "АвтоЗапчасти"
    SUPPORT_USERNAME: str = "support"

    # --- Web admin (один админ) ---
    WEB_HOST: str = "127.0.0.1"
    WEB_PORT: int = 8000
    WEB_ADMIN_USER: str = "admin"
    WEB_ADMIN_PASSWORD: str = "change_me_please"
    WEB_PUBLIC_URL: str = "http://127.0.0.1:8000"  # ссылка, которую бот отдаёт админу

    # --- VIN auto-decode (бесплатный NHTSA vPIC, без ключа) ---
    VIN_DECODE_ENABLED: bool = True
    NHTSA_URL: str = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVin"

    # --- Фото через ИИ (OpenAI-совместимый API; пусто = только менеджер) ---
    PHOTO_AI_API_KEY: str = ""
    PHOTO_AI_BASE_URL: str = "https://api.openai.com/v1"
    PHOTO_AI_MODEL: str = "gpt-4o-mini"

    @property
    def photo_ai_enabled(self) -> bool:
        return bool(self.PHOTO_AI_API_KEY.strip())

    @property
    def catalog_token(self) -> str:
        return self.CATALOG_BOT_TOKEN or self.BOT_TOKEN

    @property
    def admin_ids(self) -> set[int]:
        ids: set[int] = set()
        for part in self.ADMIN_IDS.split(","):
            part = part.strip()
            if part.isdigit():
                ids.add(int(part))
        return ids

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids


settings = Settings()
