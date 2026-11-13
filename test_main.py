"""Offline checks; no VK credentials or publishing required."""
import os
import re
import unittest
from datetime import date, timedelta
from unittest.mock import patch

import main


class HoroscopeTests(unittest.TestCase):
    DAY = date(2026, 11, 13)

    def test_one_sentence_and_three_short_hashtags_for_each_sign(self):
        for sign in main.SIGNS:
            with self.subTest(sign=sign):
                message = main.post_message(sign, self.DAY)
                body, tags = message.split("\n\n")
                self.assertEqual(len(re.findall(r"(?<!\d)[.!?](?=\s|$)", body)), 1)
                self.assertLessEqual(len(body), 180)
                self.assertEqual(len(tags.split()), 3)
                for tag in tags.split():
                    self.assertRegex(tag, r"^#[А-Яа-яЁё]+$")
                    self.assertLessEqual(len(tag), 12)
                main.validate_message(message)

    def test_same_sign_has_400_distinct_advice_combinations(self):
        for sign in main.SIGNS:
            texts = set()
            for day_offset in range(400):
                day = self.DAY + timedelta(days=day_offset)
                advice = main.horoscope(sign, day.isoformat())
                self.assertNotIn(advice, texts)
                texts.add(advice)
            self.assertEqual(len(texts), 400)

    def test_same_date_is_deterministic(self):
        self.assertEqual(main.post_message("Овен", self.DAY),
                         main.post_message("Овен", self.DAY))

    def test_reject_extra_sentences_and_numeric_hashtags(self):
        valid = main.post_message("Овен", self.DAY)
        for invalid in (
            valid.replace("#зодиак", "#зодиак2026"),
            valid.replace("#гороскоп", "#гороскоп_abc"),
            valid.replace("#зодиак", "#оченьоченьдлинныйхэштег"),
            valid.replace("#зодиак", "#зодиак #звёзды"),
            valid.replace(".\n\n", ". Ещё одно предложение.\n\n"),
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    main.validate_message(invalid)

    def test_detect_new_and_old_post_formats(self):
        current = main.post_message("Овен", self.DAY)
        old = "🔮 ГОРОСКОП НА 13.11.2026\nЗНАК: ТЕЛЕЦ\n\nСтарый текст."
        self.assertEqual(main.post_sign_for_day(current, self.DAY), "Овен")
        self.assertEqual(main.post_sign_for_day(old, self.DAY), "Телец")
        self.assertIsNone(main.post_sign_for_day(current, date(2026, 11, 14)))
        self.assertIsNone(main.post_sign_for_day("Произвольная публикация", self.DAY))

    def test_read_both_published_and_postponed_posts(self):
        old = "🔮 ГОРОСКОП НА 13.11.2026\nЗНАК: ОВЕН\n\nСтарый текст."
        new = main.post_message("Телец", self.DAY)
        calls = []

        def fake_call(token, method, params):
            self.assertEqual(method, "wall.get")
            calls.append(params["filter"])
            if params["filter"] == "postponed":
                return {"count": 1, "items": [{"text": old}]}
            return {"count": 1, "items": [{"text": new}]}

        with patch.object(main, "vk_call", side_effect=fake_call):
            existing = main.existing_signs_for_day("test_token", "243138653", self.DAY)
        self.assertEqual(existing, {"Овен", "Телец"})
        self.assertEqual(calls, ["postponed", "owner"])

    def test_fail_closed_if_vk_cannot_be_checked(self):
        with patch.object(main, "vk_call", side_effect=RuntimeError("VK denied")):
            with self.assertRaisesRegex(RuntimeError, "VK denied"):
                main.existing_signs_for_day("test_token", "243138653", self.DAY)

    def test_no_posts_if_all_signs_are_already_present(self):
        with patch.dict(os.environ, {
            "VK_ACCESS_TOKEN": "test_token",
            "VK_GROUP_ID": "243138653",
            "PUBLISH_ENABLED": "true",
            "PREVIEW_ONLY": "false",
            "VK_CHECK_ONLY": "false",
        }):
            with patch.object(main, "existing_signs_for_day",
                              return_value=set(main.SIGNS)) as existing:
                with patch.object(main, "vk_call") as api:
                    main.main()
                    existing.assert_called_once()
                    api.assert_not_called()

    def test_preview_does_not_call_vk(self):
        with patch.dict(os.environ, {
            "PREVIEW_ONLY": "true", "VK_CHECK_ONLY": "false",
            "PUBLISH_ENABLED": "true", "VK_ACCESS_TOKEN": "",
        }):
            with patch.object(main, "vk_call") as api:
                main.main()
                api.assert_not_called()


if __name__ == "__main__":
    unittest.main()
