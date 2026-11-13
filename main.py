"""Short daily VK horoscopes with VK-side duplicate protection."""
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

VK_API = "https://api.vk.com/method"
VK_VERSION = os.getenv("VK_API_VERSION", "5.199")
TZ = ZoneInfo(os.getenv("TIMEZONE", "Europe/Moscow"))
SIGNS = [
    "Овен", "Телец", "Близнецы", "Рак", "Лев", "Дева",
    "Весы", "Скорпион", "Стрелец", "Козерог", "Водолей", "Рыбы",
]
ACTIONS = [
    "закрой одну важную задачу",
    "не трать нервы на чужой цирк",
    "сначала проверь цену",
    "выбирай свой темп",
    "отложи лишнюю суету",
    "найди время выспаться",
    "не делай трагедию из мелочи",
    "скажи прямо, чего хочешь",
    "береги силы на вечер",
    "запиши хорошую идею",
    "пропусти бессмысленный спор",
    "наведи порядок в делах",
    "разберись с тем, что бесит",
    "не обещай невозможного",
    "сделай шаг к своей цели",
    "фильтруй чужие советы",
    "оставь прошлое в покое",
    "проверь факты дважды",
    "найди повод поржать",
    "не лезь в чужие разборки",
]
ENDINGS = [
    "космос сегодня не страхует идиотов",
    "планеты не оплатят твои нервы",
    "суета и без тебя справится",
    "звёзды за здравый смысл",
    "хаос пусть гуляет мимо",
    "лишний пиздец сегодня не заказывали",
    "твой ресурс не бесконечен",
    "даже Меркурий устал от драмы",
    "спокойствие дороже понтов",
    "жизнь не обязана быть квестом",
    "пусть чужой бардак остаётся чужим",
    "удача любит трезвую голову",
    "вчерашние проблемы подождут",
    "материться можно, паниковать не обязательно",
    "мелочи не заслуживают истерики",
    "вселенная и так чудит без тебя",
    "у каждой драмы свои актёры",
    "день короче чужих просьб",
    "не всё надо спасать лично",
    "главное — не кормить тревогу",
]
MAX_SCAN = 1000


def horoscope(sign: str, day: str) -> str:
    """One sentence, 400 distinct advice combinations in consecutive days."""
    if sign not in SIGNS:
        raise ValueError(f"Неизвестный знак: {sign}")
    day_value = date.fromisoformat(day)
    count = len(ACTIONS) * len(ENDINGS)
    # 37 is coprime with 400, so each advice pair is used once per cycle.
    position = (day_value.toordinal() * 37 + SIGNS.index(sign) * 19) % count
    action = ACTIONS[position // len(ENDINGS)]
    ending = ENDINGS[position % len(ENDINGS)]
    return f"{action} — {ending}."


def post_message(sign: str, day: date) -> str:
    """Single sentence plus exactly three short hashtags without digits."""
    body = f"🔮 {sign} на {day:%d.%m.%Y}: {horoscope(sign, day.isoformat())}"
    message = body + "\n\n" + f"#{sign} #гороскоп #зодиак"
    validate_message(message)
    return message


def validate_message(message: str) -> None:
    parts = message.split("\n\n")
    if len(parts) != 2 or "\n" in parts[0] or "\n" in parts[1]:
        raise ValueError("Ожидается одно предложение и строка хэштегов")
    body, tag_line = parts
    # Date separators are followed by digits, so they do not count as sentences.
    if len(re.findall(r"(?<!\d)[.!?](?=\s|$)", body)) != 1 or not body.endswith("."):
        raise ValueError("В посте должно быть ровно одно предложение")
    if len(body) > 180:
        raise ValueError("Текст слишком длинный")
    tags = tag_line.split()
    if (len(tags) != 3 or len({tag.casefold() for tag in tags}) != 3
            or any(len(tag) > 12 or not re.fullmatch(r"#[А-Яа-яЁё]+", tag) for tag in tags)):
        raise ValueError("Нужны ровно три коротких хэштега без цифр")


def vk_call(token: str, method: str, params: dict) -> dict:
    response = requests.post(
        f"{VK_API}/{method}",
        data={**params, "access_token": token, "v": VK_VERSION},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        error = data["error"]
        raise RuntimeError(f"VK API {error.get('error_code')}: {error.get('error_msg')}")
    return data["response"]


def post_sign_for_day(text: str, day: date) -> str | None:
    """Detect both new one-line entries and previously scheduled old-format posts."""
    if not isinstance(text, str):
        return None
    date_label = day.strftime("%d.%m.%Y")
    for sign in SIGNS:
        if text.startswith(f"🔮 {sign} на {date_label}:"):
            return sign
    if f"ГОРОСКОП НА {date_label}" in text.upper():
        for sign in SIGNS:
            if re.search(rf"(?m)^ЗНАК:\s*{re.escape(sign.upper())}\s*$", text.upper()):
                return sign
    return None


def existing_signs_for_day(token: str, group_id: str, day: date) -> set[str]:
    """Read posted and postponed VK entries; do not publish on incomplete checks."""
    existing: set[str] = set()
    owner_id = -int(group_id)
    day_start = int(datetime(day.year, day.month, day.day, tzinfo=TZ).timestamp())
    for wall_filter in ("postponed", "owner"):
        offset = 0
        while True:
            response = vk_call(token, "wall.get", {
                "owner_id": owner_id, "filter": wall_filter,
                "count": 100, "offset": offset,
            })
            if not isinstance(response, dict):
                raise RuntimeError(f"Не удалось проверить записи ВК: {wall_filter}")
            items = response.get("items")
            count = response.get("count")
            if not isinstance(items, list) or not isinstance(count, int) or count < 0:
                raise RuntimeError(f"Некорректный ответ VK wall.get: {wall_filter}")
            for post in items:
                if isinstance(post, dict):
                    sign = post_sign_for_day(post.get("text", ""), day)
                    if sign:
                        existing.add(sign)
            offset += len(items)
            if offset >= count:
                break
            if not items or offset >= MAX_SCAN:
                raise RuntimeError(
                    f"Не удалось полностью проверить {wall_filter}; публикация остановлена"
                )
            if wall_filter == "owner":
                regular_dates = [
                    post.get("date")
                    for post in items
                    if isinstance(post, dict)
                    and not post.get("is_pinned")
                    and isinstance(post.get("date"), int)
                ]
                if regular_dates and max(regular_dates) < day_start:
                    break
            time.sleep(0.4)
    return existing


def main() -> None:
    token = os.getenv("VK_ACCESS_TOKEN", "").strip()
    group_id = os.getenv("VK_GROUP_ID", "243138653").strip()

    if os.getenv("VK_CHECK_ONLY", "false").lower() == "true":
        if not token:
            raise RuntimeError("Не задан VK_ACCESS_TOKEN.")
        if not group_id.isdigit():
            raise RuntimeError("VK_GROUP_ID должен быть числом без club.")
        group_data = vk_call(token, "groups.getById", {"group_id": group_id})
        group = group_data[0] if isinstance(group_data, list) else group_data
        print(f"Токен принят. Группа доступна: {group.get('name', group_id)}.")
        print("Проверка завершена, публикаций нет.")
        return

    today = datetime.now(TZ).date()
    if os.getenv("PREVIEW_ONLY", "false").lower() == "true":
        for sign in SIGNS:
            print("=" * 40)
            print(post_message(sign, today))
        print(f"Предпросмотр: 12 коротких гороскопов на {today:%d.%m.%Y}, публикаций нет.")
        return

    if os.getenv("PUBLISH_ENABLED", "false").lower() != "true":
        print("Защита включена: PUBLISH_ENABLED не равен true. Публикаций нет.")
        return
    if not token:
        raise RuntimeError("Не задан VK_ACCESS_TOKEN в секретах GitHub.")
    if not group_id.isdigit():
        raise RuntimeError("VK_GROUP_ID должен быть числом без club.")

    existing = existing_signs_for_day(token, group_id, today)
    print(f"Найдено {len(existing)} уже опубликованных или отложенных знаков на сегодня.")

    first_slot = datetime(today.year, today.month, today.day, 8, 0, tzinfo=TZ)
    first_publish = max(first_slot, datetime.now(TZ) + timedelta(minutes=2))
    posted = 0
    for index, sign in enumerate(SIGNS):
        if sign in existing:
            print(f"Пропуск: на сегодня уже есть гороскоп для знака {sign}.")
            continue
        publish_at = first_publish + timedelta(minutes=20 * index)
        message = post_message(sign, today)
        vk_call(token, "wall.post", {
            "owner_id": -int(group_id),
            "from_group": 1,
            "message": message,
            "publish_date": int(publish_at.timestamp()),
            "guid": f"zvezdy-{today.isoformat()}-{index + 1}",
        })
        existing.add(sign)
        posted += 1
        print(f"Запланирован пост: {sign}, {publish_at.isoformat()}")
        time.sleep(0.5)
    print(f"Готово: новых постов {posted}, пропущено дублей {len(SIGNS) - posted}.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        raise
