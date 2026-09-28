"""Alpaca paper orders. The live brokerage host is refused."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import date
from typing import Callable
from urllib.parse import urlparse

PAPER_HOST = "paper-api.alpaca.markets"
Transport = Callable[[str, str, dict, dict | None], tuple[int, object]]


class AlpacaError(ValueError):
    pass


def client_order_id(as_of: date, symbol: str, side: str) -> str:
    return f"mf-{as_of.strftime('%Y%m%d')}-{symbol}-{side}"[:48]


class AlpacaClient:
    def __init__(
        self,
        key: str,
        secret: str,
        base_url: str = "https://paper-api.alpaca.markets",
        transport: Transport | None = None,
    ):
        host = urlparse(base_url).netloc
        if host != PAPER_HOST:
            raise AlpacaError("shadow fund only sends orders to paper-api.alpaca.markets")
        if not str(key).strip() or not str(secret).strip():
            raise AlpacaError("Alpaca paper keys are missing")
        self.key = key
        self.secret = secret
        self.base_url = base_url.rstrip("/")
        self._transport = transport or _urllib_transport

    def get_account(self) -> dict:
        return self._call("GET", "/v2/account")

    def get_positions(self) -> list[dict]:
        payload = self._call("GET", "/v2/positions")
        return list(payload or [])

    def list_open_orders(self) -> list[dict]:
        payload = self._call("GET", "/v2/orders?status=open")
        return list(payload or [])

    def get_by_client_id(self, client_id: str) -> dict | None:
        path = f"/v2/orders:by_client_order_id?client_order_id={client_id}"
        return self._call("GET", path, missing_ok=True)

    def submit_order(self, payload: dict) -> dict:
        return self._call("POST", "/v2/orders", payload)

    def _call(self, method: str, path: str, body: dict | None = None, missing_ok: bool = False):
        status, payload = self._transport(
            method,
            self.base_url + path,
            {
                "APCA-API-KEY-ID": self.key,
                "APCA-API-SECRET-KEY": self.secret,
                "Content-Type": "application/json",
            },
            body,
        )
        if status == 404 and missing_ok:
            return None
        if status >= 400:
            raise AlpacaError(f"Alpaca {status}: {payload}")
        return payload


def from_env() -> AlpacaClient:
    key = os.environ.get("APCA_API_KEY_ID", "")
    secret = os.environ.get("APCA_API_SECRET_KEY", "")
    base = os.environ.get("APCA_API_BASE_URL", "https://paper-api.alpaca.markets")
    return AlpacaClient(key, secret, base)


def submit_orders(
    client: AlpacaClient,
    orders: list[dict],
    *,
    as_of: date,
    time_in_force: str = "opg",
) -> list[dict]:
    """Sells first. A client order id already at Alpaca is not sent again."""
    sells = [o for o in orders if o.get("side") == "sell"]
    buys = [o for o in orders if o.get("side") == "buy"]
    sent = []
    for order in sells + buys:
        if order.get("status") == "rejected" or int(order.get("shares") or 0) <= 0:
            continue
        cid = client_order_id(as_of, str(order["symbol"]), str(order["side"]))
        existing = client.get_by_client_id(cid)
        if existing:
            sent.append(_from_broker(existing, order, duplicate=True))
            continue
        created = client.submit_order(
            {
                "symbol": str(order["symbol"]),
                "qty": str(int(order["shares"])),
                "side": str(order["side"]),
                "type": "market",
                "time_in_force": time_in_force,
                "client_order_id": cid,
            }
        )
        sent.append(_from_broker(created, order, duplicate=False))
    return sent


def snapshot(client: AlpacaClient) -> tuple[float, dict[str, float]]:
    account = client.get_account()
    cash = float(account.get("cash") or 0.0)
    positions = {}
    for row in client.get_positions():
        qty = float(row.get("qty") or 0.0)
        if qty > 0:
            positions[str(row["symbol"])] = qty
    return cash, positions


def _from_broker(payload: dict, order: dict, *, duplicate: bool) -> dict:
    return {
        "symbol": order.get("symbol"),
        "side": order.get("side"),
        "shares": int(order.get("shares") or 0),
        "broker_status": payload.get("status"),
        "broker_id": payload.get("id"),
        "client_order_id": payload.get("client_order_id"),
        "duplicate": duplicate,
    }


def _urllib_transport(method: str, url: str, headers: dict, body: dict | None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            payload = json.loads(raw) if raw else raw
        except json.JSONDecodeError:
            payload = raw
        return exc.code, payload
