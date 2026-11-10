import json
import os
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

VK_API = "https://api.vk.com/method"
VK_VERSION = os.getenv("VK_API_VERSION", "5.199")
MOSCOW = ZoneInfo("Europe/Moscow")
SIGNS = [
    "Овен", "Телец", "Близнецы", "Рак", "Лев", "Дева",
    "Весы", "Скорпион", "Стрелец", "Козерог", "Водолей", "Рыбы",
]


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Не задана переменная окружения {name}")
    return value


def generate_horoscopes(api_key: str, model: str, date_text: str) -> dict[str, str]:
    prompt = f"""
Напиши 12 отдельных развлекательных гороскопов на дату {date_text}, по одному для каждого знака:
{", ".join(SIGNS)}.

Стиль паблика «Звёзды охуели»: дерзкий, смешной, разговорный русский язык,
обильный, но естественный мат; без оскорблений по защищённым признакам,
без угроз и без опасных медицинских/финансовых советов.
Каждый текст 450–650 знаков, уникальный по смыслу и формулировкам.
В каждом: короткий цепляющий заход, прогноз на день, конкретный смешной совет.
Не утверждай, что это реальные предсказания: это юмор и развлечение.
Верни только корректный JSON-объект, где ключи — названия знаков из списка,
а значения — готовые тексты постов. Не добавляй Markdown и пояснения.
"""
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "temperature": 1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "Ты автор юмористического русскоязычного паблика."},
                {"role": "user", "content": prompt},
            ],
        },
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()
    content = data["choices"][0]["message"]["content"]
    result = json.loads(content)
    missing = [sign for sign in SIGNS if not isinstance(result.get(sign), str) or not result[sign].strip()]
    if missing:
        raise RuntimeError("ИИ не вернул тексты для знаков: " + ", ".join(missing))
    return {sign: result[sign].strip() for sign in SIGNS}


def vk_call(token: str, method: str, params: dict) -> dict:
    payload = {**params, "access_token": token, "v": VK_VERSION}
    response = requests.post(f"{VK_API}/{method}", data=payload, timeout=30)
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        error = data["error"]
        raise RuntimeError(f"VK API {error.get('error_code')}: {error.get('error_msg')}")
    return data["response"]


def main() -> None:
    if os.getenv("PUBLISH_ENABLED", "false").lower() != "true":
        print("Защита включена: PUBLISH_ENABLED не равен true. Публикации не отправлены.")
        return

    token = require_env("VK_ACCESS_TOKEN")
    group_id = int(require_env("VK_GROUP_ID"))
    openai_key = require_env("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")

    now = datetime.now(MOSCOW)
    publish_day = now.date() + timedelta(days=1)
    date_text = publish_day.strftime("%d.%m.%Y")
    horoscopes = generate_horoscopes(openai_key, model, date_text)

    # 09:00–20:00 по Москве: один пост в час, отдельно для каждого знака.
    for index, sign in enumerate(SIGNS):
        publish_at = datetime(
            publish_day.year, publish_day.month, publish_day.day,
            9 + index, 0, tzinfo=MOSCOW
        )
        message = (
            f"♈️ ГОРОСКОП НА {date_text}\n"
            f"ЗНАК: {sign.upper()}\n\n"
            f"{horoscopes[sign]}\n\n"
            "🔮 «Звёзды охуели» — юмор, а не руководство к жизни."
        )
        vk_call(
            token,
            "wall.post",
            {
                "owner_id": -group_id,
                "from_group": 1,
                "message": message,
                "publish_date": int(publish_at.timestamp()),
                # Стабильный GUID снижает риск повторной постановки того же поста.
                "guid": f"zvezdy-{publish_day.isoformat()}-{index + 1}",
            },
        )
        print(f"Запланирован пост: {sign}, {publish_at.isoformat()}")
        time.sleep(0.35)

    print(f"Готово: запланировано 12 постов на {date_text}.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        raise
