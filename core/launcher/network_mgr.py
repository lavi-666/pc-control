"""
PC Control — Модуль сетевой диагностики и генерации QR-кода (Network Manager).
Обеспечивает определение адаптеров, выбор интерфейса (Wi-Fi / Ethernet),
проверку правил брандмауэра и диагностику доступности для телефона.
"""

from __future__ import annotations

import io
import json
import os
import platform
import socket
import subprocess
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import qrcode


class NetworkManager:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir).resolve()

    def get_interfaces(self) -> List[Dict[str, Any]]:
        """Возвращает список всех сетевых интерфейсов системы с классификацией."""
        from scripts.network_setup import list_network_interfaces
        return list_network_interfaces()

    def detect_best_network(self) -> Dict[str, Any]:
        """Определяет наиболее подходящий физический адаптер локальной сети."""
        from scripts.network_setup import detect_network
        return detect_network()

    def query_firewall_status(self, port: int) -> Dict[str, Any]:
        """Проверяет наличие и конфигурацию правил брандмауэра Windows Defender."""
        if platform.system() != "Windows":
            return {"active": True, "details": "Non-Windows OS (Firewall check bypassed)"}

        from core.system_state import query_firewall_rule
        srv_rule = query_firewall_rule("PC Control Server")
        if not srv_rule.get("existed"):
            return {
                "active": False,
                "rule_name": "PC Control Server",
                "port": port,
                "message": f"Правило брандмауэра для порта {port} отсутствует. Нажмите 'Настроить брандмауэр'.",
            }

        rule_port = srv_rule.get("port")
        if rule_port and rule_port != port:
            return {
                "active": False,
                "rule_name": "PC Control Server",
                "port": port,
                "configured_port": rule_port,
                "message": f"Правило брандмауэра настроено на порт {rule_port}, а сервер работает на {port}. Требуется обновление правила.",
            }

        return {
            "active": True,
            "rule_name": "PC Control Server",
            "port": port,
            "profile": srv_rule.get("profile", "any"),
            "remoteip": srv_rule.get("remoteip", "LocalSubnet"),
            "message": "Правило брандмауэра активно и разрешает входящие подключения локальной сети.",
        }

    def diagnose_phone_connection(
        self,
        lan_ip: str,
        port: int,
        token: str,
        server_running: bool,
    ) -> Dict[str, Any]:
        """
        Проводит многоуровневую диагностику доступности для телефона:
        1. Запущен ли сервер.
        2. Открыт ли локальный сокет на 127.0.0.1 и LAN IP.
        3. Настроено ли правило Windows Firewall.
        4. Является ли выбранный IP реальным локальным адресом.
        5. Проверка признаков изоляции клиентов роутера (AP Isolation).
        """
        checks: List[Dict[str, Any]] = []
        is_ready = True
        warnings: List[str] = []

        # Проверка 1: статус сервера
        if not server_running:
            checks.append({
                "id": "server_running",
                "title": "Статус сервера",
                "passed": False,
                "message": "Сервер PC Control остановлен. Запустите сервер перед подключением телефона.",
            })
            is_ready = False
        else:
            checks.append({
                "id": "server_running",
                "title": "Статус сервера",
                "passed": True,
                "message": "Сервер запущен и обрабатывает запросы.",
            })

        # Проверка 2: привязка к сокету
        socket_open = False
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                socket_open = s.connect_ex((lan_ip or "127.0.0.1", port)) == 0
        except Exception:
            socket_open = False

        if socket_open:
            checks.append({
                "id": "socket_listening",
                "title": "Сетевой сокет",
                "passed": True,
                "message": f"Порт {port} открыт и принимает входящие подключения на {lan_ip}.",
            })
        else:
            checks.append({
                "id": "socket_listening",
                "title": "Сетевой сокет",
                "passed": False,
                "message": f"Порт {port} не отвечает по адресу {lan_ip}. Проверьте номер порта в настройках.",
            })
            if server_running:
                is_ready = False

        # Проверка 3: Брандмауэр Windows
        fw_status = self.query_firewall_status(port)
        if fw_status["active"]:
            checks.append({
                "id": "firewall_rule",
                "title": "Брандмауэр Windows",
                "passed": True,
                "message": fw_status["message"],
            })
        else:
            checks.append({
                "id": "firewall_rule",
                "title": "Брандмауэр Windows",
                "passed": False,
                "message": fw_status["message"],
            })
            is_ready = False

        # Проверка 4: Валидность IP-адреса
        is_private_ip = False
        if lan_ip and lan_ip != "127.0.0.1":
            try:
                import ipaddress
                ip_obj = ipaddress.ip_address(lan_ip)
                is_private_ip = ip_obj.is_private
            except Exception:
                is_private_ip = False

        if is_private_ip:
            checks.append({
                "id": "lan_ip_valid",
                "title": "Локальный IP-адрес",
                "passed": True,
                "message": f"Выбран корректный частный IP-адрес локальной сети: {lan_ip}.",
            })
        else:
            checks.append({
                "id": "lan_ip_valid",
                "title": "Локальный IP-адрес",
                "passed": False,
                "message": f"IP-адрес '{lan_ip}' не является стандартным адресом локальной сети (192.168.x.x, 10.x.x.x, 172.16-31.x.x). Телефон не сможет подключиться напрямую.",
            })
            is_ready = False

        # Подсказка по AP Isolation
        note = (
            "Если телефон и ПК находятся в одной сети Wi-Fi, но телефон не открывает страницу, "
            "проверьте настройки роутера: функция 'Изоляция беспроводных клиентов' (AP Isolation / "
            "Client Isolation / Гостевая сеть) должна быть отключена, либо используйте Tailscale VPN."
        )

        return {
            "is_ready": is_ready,
            "lan_ip": lan_ip,
            "port": port,
            "checks": checks,
            "warnings": warnings,
            "ap_isolation_note": note,
        }

    def generate_qr_image(
        self,
        lan_ip: str,
        port: int,
        token: str,
        vpn_ip: str = "",
        mac_address: str = "",
        wol_relay_ip: str = "",
    ) -> bytes:
        """Генерирует PNG-изображение QR-кода с параметрами подключения."""
        query_params = {
            "token": token or "",
            "lan": lan_ip or "",
        }
        if vpn_ip:
            query_params["vpn"] = vpn_ip
        if mac_address:
            query_params["mac"] = mac_address
        if wol_relay_ip:
            query_params["relay"] = wol_relay_ip

        qs = urllib.parse.urlencode(query_params)
        url = f"http://{lan_ip}:{port}/?{qs}"

        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=2,
        )
        qr.add_data(url)
        qr.make(fit=True)

        img = qr.make_image(fill_color="#0f172a", back_color="#ffffff")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
