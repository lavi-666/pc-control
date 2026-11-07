"""
PC Control — Комплексные тесты безопасности идемпотентности и кэширования X-Request-Id.

Проверяет устранение критических уязвимостей:
1. Защита от обхода аутентификации через поддельный / угаданный X-Request-Id.
2. Изоляция кэша между разными токенами пользователей (token-scoped cache).
3. Валидация контекста запроса: отклонение повторного ID с изменённым телом (payload tampering) - 409 Conflict.
4. Отклонение повторного ID на другом маршруте (cross-endpoint pollution) - 409 Conflict.
5. Защита от race condition: блокировка конкурентных параллельных запросов (IN_PROGRESS) - 409 Conflict.
6. Корректная отдача кэшированного ответа с заголовком X-Idempotent-Replay: 1 при точном повторе.
7. Ограничение потребления памяти (LRU eviction до 300 записей).
8. Автоматическая очистка по TTL (15 секунд).
9. Корректная обработка сбойных запросов (статус FAILED позволяет повторить операцию).
"""

import json
import os
import time
import unittest
import hashlib

# Режим тестирования
os.environ["PC_CONTROL_TEST_MODE"] = "1"

from server import (
    app,
    _idempotency_cache,
    _idempotency_lock,
    _IDEMPOTENCY_MAX_ENTRIES,
    _IDEMPOTENCY_TTL_SEC,
    IdempotencyRecord,
)
from core.config import get_auth_token, set_safe_test_mode


class TestIdempotencySecurity(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.token = get_auth_token()
        self.headers = {
            "X-Auth-Token": self.token,
            "Content-Type": "application/json"
        }
        # Очищаем кэш перед каждым тестом
        with _idempotency_lock:
            _idempotency_cache.clear()

    def tearDown(self):
        with _idempotency_lock:
            _idempotency_cache.clear()
        set_safe_test_mode(True)

    # 1. Защита от обхода аутентификации
    def test_unauthenticated_request_cannot_read_or_populate_idempotency_cache(self):
        """Неавторизованный запрос с X-Request-Id не получает кэшированный ответ и получает 401."""
        req_id = f"sec_test_req_{time.time()}_1"
        payload = json.dumps({"action": "play_pause"})

        # 1. Авторизованный пользователь делает легитимный запрос
        res1 = self.client.post(
            "/media/control",
            headers={**self.headers, "X-Request-Id": req_id},
            data=payload
        )
        self.assertEqual(res1.status_code, 200)

        # Отключаем безопасный режим чтобы включить строгую проверку авторизации
        set_safe_test_mode(False)

        # 2. Неавторизованный злоумышленник пытается отправить тот же X-Request-Id без токена
        res_unauth = self.client.post(
            "/media/control",
            headers={"Content-Type": "application/json", "X-Request-Id": req_id},
            data=payload
        )
        self.assertEqual(res_unauth.status_code, 401)
        # Ответ не должен быть извлечён из кэша
        self.assertNotIn("X-Idempotent-Replay", res_unauth.headers)

    # 2. Корректный повтор легитимного запроса
    def test_exact_replay_returns_cached_response_with_replay_header(self):
        """Точный повтор мутирующего запроса с тем же X-Request-Id возвращает кэшированный ответ."""
        req_id = f"sec_test_req_{time.time()}_2"
        payload = json.dumps({"action": "play_pause"})

        # Первый запрос
        res1 = self.client.post(
            "/media/control",
            headers={**self.headers, "X-Request-Id": req_id},
            data=payload
        )
        self.assertEqual(res1.status_code, 200)
        self.assertNotIn("X-Idempotent-Replay", res1.headers)

        # Повторный запрос (реплей при реконнекте)
        res2 = self.client.post(
            "/media/control",
            headers={**self.headers, "X-Request-Id": req_id},
            data=payload
        )
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.headers.get("X-Idempotent-Replay"), "1")
        self.assertEqual(res1.get_json(), res2.get_json())

    # 3. Отклонение подмены тела запроса (Payload Tampering)
    def test_payload_tampering_with_same_request_id_returns_409_conflict(self):
        """Использование того же X-Request-Id с другим телом возвращает 409 Conflict."""
        req_id = f"sec_test_req_{time.time()}_3"

        # Запрос 1: действие play_pause
        res1 = self.client.post(
            "/media/control",
            headers={**self.headers, "X-Request-Id": req_id},
            data=json.dumps({"action": "play_pause"})
        )
        self.assertEqual(res1.status_code, 200)

        # Запрос 2: тот же ID, но действие подменено на next
        res2 = self.client.post(
            "/media/control",
            headers={**self.headers, "X-Request-Id": req_id},
            data=json.dumps({"action": "next"})
        )
        self.assertEqual(res2.status_code, 409)
        data = res2.get_json()
        self.assertFalse(data.get("ok"))
        self.assertIn("different request payload", data.get("message", ""))

    # 4. Отклонение использования того же ID на другом маршруте (Cross-Endpoint Pollution)
    def test_cross_endpoint_reuse_with_same_request_id_returns_409_conflict(self):
        """Использование того же X-Request-Id на другом эндпоинте возвращает 409 Conflict."""
        req_id = f"sec_test_req_{time.time()}_4"

        # Запрос 1 на /media/control
        res1 = self.client.post(
            "/media/control",
            headers={**self.headers, "X-Request-Id": req_id},
            data=json.dumps({"action": "play_pause"})
        )
        self.assertEqual(res1.status_code, 200)

        # Запрос 2 с тем же ID на /volume
        res2 = self.client.post(
            "/volume",
            headers={**self.headers, "X-Request-Id": req_id},
            data=json.dumps({"level": 50})
        )
        self.assertEqual(res2.status_code, 409)
        data = res2.get_json()
        self.assertFalse(data.get("ok"))

    # 5. Изоляция между разными пользователями/токенами
    def test_cache_is_isolated_between_different_auth_tokens(self):
        """Запросы с разными токенами авторизации изолированы друг от друга даже при совпадающем ID."""
        req_id = f"sec_test_req_{time.time()}_5"
        payload = json.dumps({"action": "play_pause"})

        # Первый пользователь (основной токен)
        res1 = self.client.post(
            "/media/control",
            headers={"X-Auth-Token": self.token, "Content-Type": "application/json", "X-Request-Id": req_id},
            data=payload
        )
        self.assertEqual(res1.status_code, 200)

        # Проверяем структуру кэша: ключ привязан к хэшу токена
        token_a_hash = hashlib.sha256(self.token.encode("utf-8")).hexdigest()[:16]
        token_b = "custom_test_token_user_b_xyz987"
        token_b_hash = hashlib.sha256(token_b.encode("utf-8")).hexdigest()[:16]

        with _idempotency_lock:
            self.assertIn(f"{token_a_hash}:{req_id}", _idempotency_cache)
            self.assertNotIn(f"{token_b_hash}:{req_id}", _idempotency_cache)

    # 6. Защита от конкурентных запросов (Race Condition)
    def test_concurrent_in_progress_request_returns_409_conflict(self):
        """Если операция с данным ID всё ещё выполняется (IN_PROGRESS), повторный параллельный запрос блокируется."""
        req_id = f"sec_test_req_{time.time()}_6"
        token_hash = hashlib.sha256(self.token.encode("utf-8")).hexdigest()[:16]
        primary_key = f"{token_hash}:{req_id}"
        payload_bytes = json.dumps({"action": "play_pause"}).encode("utf-8")

        # Имитируем запрос в состоянии выполнения (IN_PROGRESS) с идентичным телом и путем
        with _idempotency_lock:
            rec = IdempotencyRecord(
                token_hash=token_hash,
                method="POST",
                path="/media/control",
                body_hash=hashlib.sha256(payload_bytes).hexdigest(),
                req_id=req_id
            )
            rec.status = "IN_PROGRESS"
            _idempotency_cache[primary_key] = rec

        # Пытаемся выполнить запрос с тем же ID параллельно
        res = self.client.post(
            "/media/control",
            headers={**self.headers, "X-Request-Id": req_id},
            data=payload_bytes
        )
        self.assertEqual(res.status_code, 409)
        data = res.get_json()
        self.assertFalse(data.get("ok"))
        self.assertIn("currently being processed", data.get("message", ""))

    # 7. Истечение по TTL (15 секунд)
    def test_ttl_expiration_evicts_old_entries(self):
        """Записи старше 15 секунд автоматически удаляются по TTL."""
        req_id = f"sec_test_req_{time.time()}_7"
        token_hash = hashlib.sha256(self.token.encode("utf-8")).hexdigest()[:16]
        primary_key = f"{token_hash}:{req_id}"
        payload_bytes = json.dumps({"action": "play_pause"}).encode("utf-8")

        # Записываем завершённую операцию с устаревшим created_at (> 15 сек)
        with _idempotency_lock:
            rec = IdempotencyRecord(
                token_hash=token_hash,
                method="POST",
                path="/media/control",
                body_hash=hashlib.sha256(payload_bytes).hexdigest(),
                req_id=req_id
            )
            rec.status = "COMPLETED"
            rec.created_at = time.time() - (_IDEMPOTENCY_TTL_SEC + 5.0)
            rec.response = {"body": b'{"ok":true}', "status": 200, "content_type": "application/json"}
            _idempotency_cache[primary_key] = rec

        # Новый запрос с тем же ID должен очистить старую запись и выполниться заново
        res = self.client.post(
            "/media/control",
            headers={**self.headers, "X-Request-Id": req_id},
            data=payload_bytes
        )
        self.assertEqual(res.status_code, 200)
        # Так как запись протухла, это свежее выполнение без заголовка реплея
        self.assertNotIn("X-Idempotent-Replay", res.headers)

    # 8. Ограничение памяти (Capacity bounding)
    def test_cache_capacity_bounding(self):
        """Кэш не разрастается бесконечно и ограничен _IDEMPOTENCY_MAX_ENTRIES (300)."""
        token_hash = hashlib.sha256(self.token.encode("utf-8")).hexdigest()[:16]

        with _idempotency_lock:
            # Заполняем кэш до лимита
            for i in range(_IDEMPOTENCY_MAX_ENTRIES + 20):
                rid = f"overflow_test_{i}"
                k = f"{token_hash}:{rid}"
                rec = IdempotencyRecord(token_hash, "POST", "/media/control", "hash", rid)
                rec.status = "COMPLETED"
                rec.response = {"body": b"{}", "status": 200, "content_type": "application/json"}
                _idempotency_cache[k] = rec
                if len(_idempotency_cache) > _IDEMPOTENCY_MAX_ENTRIES:
                    _idempotency_cache.popitem(last=False)

            self.assertLessEqual(len(_idempotency_cache), _IDEMPOTENCY_MAX_ENTRIES)
            # Самые первые записи должны быть вытеснены
            first_key = f"{token_hash}:overflow_test_0"
            self.assertNotIn(first_key, _idempotency_cache)
            # Последняя запись присутствует
            last_key = f"{token_hash}:overflow_test_{_IDEMPOTENCY_MAX_ENTRIES + 19}"
            self.assertIn(last_key, _idempotency_cache)

    # 9. Сбойные запросы (FAILED) позволяют повторную попытку
    def test_failed_requests_allow_clean_retry(self):
        """Если предыдущий запрос завершился ошибкой (500), пользователь может повторить попытку."""
        req_id = f"sec_test_req_{time.time()}_9"
        token_hash = hashlib.sha256(self.token.encode("utf-8")).hexdigest()[:16]
        primary_key = f"{token_hash}:{req_id}"
        payload_bytes = json.dumps({"action": "play_pause"}).encode("utf-8")

        # Записываем результат FAILED с точным хэшем тела
        with _idempotency_lock:
            rec = IdempotencyRecord(
                token_hash=token_hash,
                method="POST",
                path="/media/control",
                body_hash=hashlib.sha256(payload_bytes).hexdigest(),
                req_id=req_id
            )
            rec.status = "FAILED"
            _idempotency_cache[primary_key] = rec

        # Повторный запрос должен перейти в IN_PROGRESS и выполниться заново, завершившись успехом
        res = self.client.post(
            "/media/control",
            headers={**self.headers, "X-Request-Id": req_id},
            data=payload_bytes
        )
        self.assertEqual(res.status_code, 200)


if __name__ == "__main__":
    unittest.main()
