import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import requests

from app.config import (
    SAFE_DAYS,
    TPLUS_APP_TICKET,
    TPLUS_APP_TICKET_CACHE_FILE,
    TPLUS_APP_TICKET_MAX_AGE_SECONDS,
    TPLUS_AUTH_BASE_URL,
    TPLUS_AUTH_MODE,
    TPLUS_API_BASE_URL,
    TPLUS_APP_KEY,
    TPLUS_APP_SECRET,
    TPLUS_CERTIFICATE,
    TPLUS_ORG_ID,
    TPLUS_QUERY_PAGE_SIZE,
    TPLUS_REDIRECT_URI,
    TPLUS_REQUEST_TIMEOUT,
    TPLUS_RETRY_TIMES,
    TPLUS_INVENTORY_QUERY_ENDPOINT,
    TPLUS_CURRENT_STOCK_QUERY_ENDPOINT,
    TPLUS_RECENT_SALES_CACHE_FILE,
    TPLUS_RECENT_SALES_CACHE_TTL_SECONDS,
    WARNING_WAREHOUSE_CODE,
    APP_SECRET,
    TPLUS_TOKEN_CACHE_FILE,
    TPLUS_TOKEN_REFRESH_SKEW_SECONDS,
)
from app.data_sources.base import ensure_standard_columns
from app.data_sources.excel_source import clean_code, clean_size


GET_TOKEN_ENDPOINT = "/auth/v2/getToken"
REFRESH_TOKEN_ENDPOINT = "/auth/v2/refreshToken"
SELF_BUILT_GENERATE_TOKEN_ENDPOINT = "/v1/common/auth/selfBuiltApp/generateToken"
INVENTORY_QUERY_ENDPOINT = TPLUS_INVENTORY_QUERY_ENDPOINT
CURRENT_STOCK_QUERY_ENDPOINT = TPLUS_CURRENT_STOCK_QUERY_ENDPOINT
SALE_DELIVERY_FIND_VOUCHER_LIST_ENDPOINT = "/tplus/api/v2/SaleDeliveryOpenApi/FindVoucherList"
SALE_DELIVERY_GET_VOUCHER_DTO_ENDPOINT = "/tplus/api/v2/SaleDeliveryOpenApi/GetVoucherDTO"
INVENTORY_QUERY_BODY = {
    "param": {
        "SelectFields": "Code,Name,Specification,DefaultBarCode",
    }
}
CURRENT_STOCK_QUERY_BODY = {"param": {}}
SALE_DELIVERY_LIST_BODY = {
    "selectFields": [],
    "paramDic": {},
    "pageIndex": 1,
    "pageSize": 10,
}


class TPlusOpenAPIClient:
    def __init__(self):
        if not TPLUS_API_BASE_URL:
            raise ValueError("请配置 TPLUS_API_BASE_URL")

        if TPLUS_APP_KEY == "YOUR_APP_KEY" or APP_SECRET == "YOUR_APP_SECRET":
            raise ValueError("请在 .env 中配置真实的 TPLUS_APP_KEY 和 TPLUS_APP_SECRET")

        self.session = requests.Session()

    def exchange_code_for_token(self, code: str) -> dict[str, Any]:
        if not TPLUS_REDIRECT_URI:
            raise ValueError("请配置 TPLUS_REDIRECT_URI，且必须与开放平台 OAuth 回调地址一致")

        response = self._request_auth_token(
            "POST",
            GET_TOKEN_ENDPOINT,
            params={
                "grantType": "authorization_code",
                "redirectUri": TPLUS_REDIRECT_URI,
                "code": code,
            },
        )
        payload = self._extract_token_payload(response)
        self._write_cached_token(payload)
        return payload

    def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        response = self._request_auth_token(
            "POST",
            REFRESH_TOKEN_ENDPOINT,
            params={
                "grantType": "refresh_token",
                "refreshToken": refresh_token,
            },
        )
        payload = self._extract_token_payload(response)
        self._write_cached_token(payload)
        return payload

    def generate_self_built_token(self, app_ticket: str, certificate: str) -> dict[str, Any]:
        response = self._request_auth_token(
            "POST",
            SELF_BUILT_GENERATE_TOKEN_ENDPOINT,
            json={
                "appTicket": app_ticket,
                "certificate": certificate,
            },
        )
        payload = self._extract_token_payload(response)
        self._write_cached_token(payload)
        return payload

    def get_access_token(self, force_refresh: bool = False) -> str:
        cached_token = self._read_cached_token()
        if not force_refresh and self._cached_access_token_is_valid(cached_token):
            return str(cached_token["access_token"])

        if TPLUS_AUTH_MODE in {"self_built", "selfbuilt", "self-built"}:
            token_payload = self._generate_self_built_access_token()
            token = token_payload.get("access_token")
            if not token:
                raise RuntimeError(f"自建应用获取 token 成功但响应中未找到 accessToken：{token_payload}")
            return str(token)

        refresh_token = cached_token.get("refresh_token") if cached_token else None
        if not refresh_token:
            raise RuntimeError("未找到可用的 T+ refresh_token，请先访问 /tplus/oauth/callback 完成授权")

        refresh_expires_at = float(cached_token.get("refresh_token_expires_at", 0))
        if refresh_expires_at <= time.time():
            raise RuntimeError("T+ refresh_token 已过期，请重新完成 OAuth 授权")

        refreshed_token = self.refresh_access_token(str(refresh_token))
        token = refreshed_token.get("access_token")
        if not token:
            raise RuntimeError(f"刷新 T+ access_token 成功但响应中未找到 access_token：{refreshed_token}")

        return str(token)

    def _generate_self_built_access_token(self) -> dict[str, Any]:
        if not TPLUS_CERTIFICATE:
            raise RuntimeError("请在 .env 配置 TPLUS_CERTIFICATE，自建应用获取 token 必需")

        app_ticket = self._read_latest_app_ticket()
        if not app_ticket:
            raise RuntimeError("未找到可用的 appTicket，请先配置消息接收地址并等待平台推送")

        return self.generate_self_built_token(app_ticket, TPLUS_CERTIFICATE)

    def query_inventory(self) -> list[dict[str, Any]]:
        response = self._request("POST", INVENTORY_QUERY_ENDPOINT, json=INVENTORY_QUERY_BODY)
        return self._extract_records(response)

    def query_current_stock(self) -> list[dict[str, Any]]:
        response = self._request("POST", CURRENT_STOCK_QUERY_ENDPOINT, json=CURRENT_STOCK_QUERY_BODY)
        return self._extract_records(response)

    def find_sale_delivery_list(
        self,
        page_index: int = 1,
        page_size: int = 10,
        param_dic: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        body = dict(SALE_DELIVERY_LIST_BODY)
        body["paramDic"] = param_dic or {}
        body["pageIndex"] = page_index
        body["pageSize"] = page_size
        response = self._post_json_direct(
            SALE_DELIVERY_FIND_VOUCHER_LIST_ENDPOINT,
            body,
        )
        return _parse_columns_rows_response(response)

    def _find_sale_delivery_list_response(
        self,
        page_index: int = 1,
        page_size: int = 10,
        param_dic: dict[str, Any] | None = None,
        debug: bool = True,
    ) -> dict[str, Any]:
        body = dict(SALE_DELIVERY_LIST_BODY)
        body["paramDic"] = param_dic or {}
        body["pageIndex"] = page_index
        body["pageSize"] = page_size
        response = self._post_json_direct(
            SALE_DELIVERY_FIND_VOUCHER_LIST_ENDPOINT,
            body,
            debug=debug,
        )
        return response if isinstance(response, dict) else {"data": response}

    def get_sale_delivery_detail(
        self,
        voucher_id: str | int | None = None,
        voucher_code: str | None = None,
        debug: bool = True,
    ) -> dict[str, Any]:
        if voucher_id is None and not voucher_code:
            raise ValueError("voucher_id 或 voucher_code 至少传一个")

        if voucher_id is not None:
            try:
                response = self._post_json_direct(
                    SALE_DELIVERY_GET_VOUCHER_DTO_ENDPOINT,
                    {"param": {"voucherID": voucher_id}},
                    debug=debug,
                )
                return response if isinstance(response, dict) else {"data": response}
            except Exception:
                if not voucher_code:
                    raise

        response = self._post_json_direct(
            SALE_DELIVERY_GET_VOUCHER_DTO_ENDPOINT,
            {"param": {"voucherCode": voucher_code}},
            debug=debug,
        )
        return response if isinstance(response, dict) else {"data": response}

    def query_recent_sale_delivery_sales(
        self,
        days: int = SAFE_DAYS,
        page_size: int = 100,
        max_pages: int = 10,
        max_detail_workers: int = 8,
        param_dic: dict[str, Any] | None = None,
        end_date: date | None = None,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        end = end_date or date.today()
        start = end - timedelta(days=days - 1)
        cache_key = {
            "version": 3,
            "days": days,
            "end_date": end.isoformat(),
            "param_dic": param_dic or {},
        }
        if not force_refresh:
            cached_sales_df = _read_recent_sales_cache(cache_key)
            if cached_sales_df is not None:
                return cached_sales_df

        first_page = self._find_sale_delivery_list_response(
            page_index=1,
            page_size=page_size,
            param_dic=param_dic,
            debug=False,
        )
        total_pages = _to_int(_dig(first_page, "data", "TotalPageNum")) or 1

        candidate_vouchers_by_key: dict[tuple[Any, Any], dict[str, Any]] = {}
        scanned_pages: set[int] = set()

        def scan_page(page_index: int) -> bool:
            if page_index == 1:
                list_response = first_page
            else:
                list_response = self._find_sale_delivery_list_response(
                    page_index=page_index,
                    page_size=page_size,
                    param_dic=param_dic,
                    debug=False,
                )
            scanned_pages.add(page_index)
            vouchers = _parse_columns_rows_response(list_response)
            page_dates = [
                voucher_date
                for voucher_date in (_extract_voucher_code_date(voucher) for voucher in vouchers)
                if voucher_date is not None
            ]

            for voucher in vouchers:
                voucher_code_date = _extract_voucher_code_date(voucher)
                if voucher_code_date is not None and (voucher_code_date < start or voucher_code_date > end):
                    continue
                if voucher_code_date is None and not param_dic:
                    continue

                voucher_id = voucher.get("id")
                voucher_code = voucher.get("code")
                if not voucher_id and not voucher_code:
                    continue

                candidate_vouchers_by_key[(voucher_id, voucher_code)] = voucher

            return bool(page_dates and max(page_dates) < start)

        last_page_to_scan = min(total_pages, max_pages)
        for page_index in range(1, last_page_to_scan + 1):
            if scan_page(page_index):
                break

        first_tail_page = max(1, total_pages - max_pages + 1)
        for page_index in range(total_pages, first_tail_page - 1, -1):
            if page_index in scanned_pages:
                continue
            scan_page(page_index)

        candidate_vouchers = list(candidate_vouchers_by_key.values())

        rows: list[dict[str, Any]] = []
        worker_count = max(1, min(max_detail_workers, len(candidate_vouchers) or 1))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [
                executor.submit(
                    self.get_sale_delivery_detail,
                    voucher_id=voucher.get("id"),
                    voucher_code=voucher.get("code"),
                    debug=False,
                )
                for voucher in candidate_vouchers
            ]
            for future in as_completed(futures):
                try:
                    detail_response = future.result()
                except Exception as exc:
                    print(f"[DEBUG-SALE-DELIVERY] skip detail error: {exc}")
                    continue
                rows.extend(_extract_sale_delivery_sales_rows(detail_response, start, end))

        if not rows:
            empty_result = pd.DataFrame(columns=["存货编码", "尺码", "近7天销量", "日均销量"])
            _write_recent_sales_cache(cache_key, empty_result)
            return empty_result

        result = _build_recent_sales_summary_df(rows, days)
        _write_recent_sales_cache(cache_key, result)
        return result

    def _post_json_direct(self, endpoint: str, body: dict[str, Any], debug: bool = True) -> Any:
        url = f"{TPLUS_API_BASE_URL}{endpoint}"
        headers = {
            "openToken": self.get_access_token(),
            "appKey": TPLUS_APP_KEY,
            "appSecret": APP_SECRET,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        if debug:
            _debug_sale_delivery_request(url, headers, body)
        response = requests.post(url, headers=headers, json=body, timeout=TPLUS_REQUEST_TIMEOUT)
        try:
            result = response.json()
        except ValueError:
            result = {"raw_text": response.text}

        if debug:
            _debug_sale_delivery_response(response.status_code, result, url, headers, body)
        if isinstance(result, dict) and _is_api_error(result):
            raise RuntimeError(f"{result.get('code')}: {result.get('message') or result}")

        return result

    def _query_all_pages(self, endpoint: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        page_index = 1

        while True:
            response = self._request(
                "POST",
                endpoint,
                json={
                    "pageIndex": page_index,
                    "pageSize": TPLUS_QUERY_PAGE_SIZE,
                },
            )
            page_records = self._extract_records(response)
            records.extend(page_records)

            total_count = self._extract_total_count(response)
            if total_count is not None and len(records) >= total_count:
                break

            if len(page_records) < TPLUS_QUERY_PAGE_SIZE:
                break

            page_index += 1

        return records

    def _request(
        self,
        method: str,
        endpoint: str,
        include_token: bool = True,
        **kwargs,
    ) -> dict[str, Any]:
        url = f"{TPLUS_API_BASE_URL}{endpoint}"
        debug_business_request = endpoint in {
            "/tplus/api/v2/inventory/Query",
            "/tplus/api/v2/currentStock/Query",
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "appKey": TPLUS_APP_KEY,
            "appSecret": TPLUS_APP_SECRET,
        }

        if include_token:
            headers["openToken"] = self.get_access_token()
            sid = self._read_cached_sid()
            if sid:
                headers["Cookie"] = f"sid={sid}"

        last_error = None
        for attempt in range(1, TPLUS_RETRY_TIMES + 1):
            response_logged = False
            try:
                if debug_business_request:
                    _debug_tplus_business_request(url, headers, kwargs)
                response = self.session.request(
                    method,
                    url,
                    headers=headers,
                    timeout=TPLUS_REQUEST_TIMEOUT,
                    **kwargs,
                )

                if response.status_code in {401, 403} and include_token:
                    headers["openToken"] = self.get_access_token(force_refresh=True)
                    sid = self._read_cached_sid()
                    if sid:
                        headers["Cookie"] = f"sid={sid}"
                    response = self.session.request(
                        method,
                        url,
                        headers=headers,
                        timeout=TPLUS_REQUEST_TIMEOUT,
                        **kwargs,
                    )

                response.raise_for_status()
                result = response.json()
                if debug_business_request:
                    _debug_tplus_business_response(response.status_code, result)
                    if _is_exsv0011_response(result):
                        _debug_tplus_curl(url, headers, kwargs)
                    response_logged = True
                self._raise_for_api_error(result)
                return result
            except (requests.RequestException, ValueError, RuntimeError) as exc:
                if debug_business_request and not response_logged and "response" in locals():
                    _debug_tplus_business_response_from_error(response)
                last_error = exc
                if attempt >= TPLUS_RETRY_TIMES:
                    break
                time.sleep(2 ** (attempt - 1))

        raise RuntimeError(_format_tplus_request_error(last_error, endpoint)) from last_error

    def _request_auth_token(self, method: str, endpoint: str, **kwargs) -> dict[str, Any]:
        url = f"{TPLUS_AUTH_BASE_URL}{endpoint}"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "appKey": TPLUS_APP_KEY,
            "appSecret": TPLUS_APP_SECRET,
        }

        last_error = None
        for attempt in range(1, TPLUS_RETRY_TIMES + 1):
            try:
                request_kwargs = dict(kwargs)
                request_kwargs.setdefault("json", {})
                response = self.session.request(
                    method,
                    url,
                    headers=headers,
                    timeout=TPLUS_REQUEST_TIMEOUT,
                    **request_kwargs,
                )
                result = response.json()
                if endpoint == SELF_BUILT_GENERATE_TOKEN_ENDPOINT:
                    _debug_generate_token_response(result)
                self._raise_for_api_error(result)
                response.raise_for_status()
                return result
            except (requests.RequestException, ValueError, RuntimeError) as exc:
                last_error = exc
                if attempt >= TPLUS_RETRY_TIMES:
                    break
                time.sleep(2 ** (attempt - 1))

        raise RuntimeError(f"调用畅捷通 T+ OpenAPI Token 接口失败：{last_error}") from last_error

    def _read_cached_token(self) -> dict[str, Any] | None:
        if not os.path.exists(TPLUS_TOKEN_CACHE_FILE):
            return None

        try:
            with open(TPLUS_TOKEN_CACHE_FILE, "r", encoding="utf-8") as file:
                payload = json.load(file)
        except (OSError, json.JSONDecodeError):
            return None

        if isinstance(payload, dict):
            return payload

        return None

    @staticmethod
    def _cached_access_token_is_valid(payload: dict[str, Any] | None) -> bool:
        if not payload:
            return False

        token = payload.get("access_token")
        expires_at = float(payload.get("access_token_expires_at") or payload.get("expires_at") or 0)
        return bool(token) and expires_at - TPLUS_TOKEN_REFRESH_SKEW_SECONDS > time.time()

    def _write_cached_token(self, payload: dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(TPLUS_TOKEN_CACHE_FILE), exist_ok=True)
        now = time.time()
        existing_payload = self._read_cached_token() or {}
        cache_payload = {
            "access_token": payload.get("access_token") or existing_payload.get("access_token"),
            "refresh_token": payload.get("refresh_token") or existing_payload.get("refresh_token"),
            "access_token_expires_at": now + int(payload.get("expires_in") or 0),
            "refresh_token_expires_at": now + int(payload.get("refresh_expires_in") or 0),
            "org_id": payload.get("org_id") or existing_payload.get("org_id"),
            "user_id": payload.get("user_id") or existing_payload.get("user_id"),
            "app_name": payload.get("app_name") or existing_payload.get("app_name"),
            "scope": payload.get("scope") or existing_payload.get("scope"),
            "user_auth_permanent_code": payload.get("user_auth_permanent_code")
            or existing_payload.get("user_auth_permanent_code"),
            "sid": payload.get("sid") or existing_payload.get("sid"),
            "updated_at": now,
        }
        with open(TPLUS_TOKEN_CACHE_FILE, "w", encoding="utf-8") as file:
            json.dump(cache_payload, file, ensure_ascii=False, indent=2)

    def _read_cached_sid(self) -> str | None:
        cached_token = self._read_cached_token()
        sid = cached_token.get("sid") if cached_token else None
        return str(sid) if sid else None

    def save_app_ticket(self, payload: dict[str, Any]) -> str:
        app_ticket = _extract_app_ticket(payload)
        if not app_ticket:
            raise ValueError(f"消息回调中未找到 appTicket：{payload}")

        os.makedirs(os.path.dirname(TPLUS_APP_TICKET_CACHE_FILE), exist_ok=True)
        cache_payload = {
            "app_ticket": app_ticket,
            "received_at": time.time(),
            "raw_payload": payload,
        }
        with open(TPLUS_APP_TICKET_CACHE_FILE, "w", encoding="utf-8") as file:
            json.dump(cache_payload, file, ensure_ascii=False, indent=2)

        return app_ticket

    def _read_latest_app_ticket(self) -> str | None:
        if TPLUS_APP_TICKET:
            return TPLUS_APP_TICKET

        if not os.path.exists(TPLUS_APP_TICKET_CACHE_FILE):
            return None

        try:
            with open(TPLUS_APP_TICKET_CACHE_FILE, "r", encoding="utf-8") as file:
                payload = json.load(file)
        except (OSError, json.JSONDecodeError):
            return None

        if not isinstance(payload, dict):
            return None

        received_at = float(payload.get("received_at") or 0)
        if received_at + TPLUS_APP_TICKET_MAX_AGE_SECONDS <= time.time():
            return None

        app_ticket = payload.get("app_ticket")
        return str(app_ticket) if app_ticket else None

    def _clear_cached_token(self) -> None:
        try:
            os.remove(TPLUS_TOKEN_CACHE_FILE)
        except FileNotFoundError:
            pass

    @staticmethod
    def _extract_token_payload(response: dict[str, Any]) -> dict[str, Any]:
        payload = response.get("result")
        if payload is True:
            payload = response.get("value")

        if not isinstance(payload, dict):
            raise RuntimeError(f"Token 接口响应中未找到 result：{response}")

        normalized_payload = _normalize_token_payload(payload)

        if not normalized_payload.get("access_token") or not normalized_payload.get("refresh_token"):
            raise RuntimeError(f"Token 接口响应中缺少 access_token 或 refresh_token：{response}")

        return normalized_payload

    @staticmethod
    def _extract_token(response: dict[str, Any]) -> str:
        candidates = [
            response.get("access_token"),
            response.get("accessToken"),
            response.get("token"),
            _dig(response, "data", "access_token"),
            _dig(response, "data", "accessToken"),
            _dig(response, "data", "token"),
        ]
        token = next((value for value in candidates if value), None)
        if not token:
            raise RuntimeError(f"获取 token 成功但响应中未找到 access token：{response}")

        return str(token)

    @staticmethod
    def _extract_records(response: Any) -> list[dict[str, Any]]:
        if isinstance(response, list):
            return [item for item in response if isinstance(item, dict)]

        data = response.get("data", response)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]

        if not isinstance(data, dict):
            return []

        for key in ("rows", "Rows", "items", "Items", "list", "List", "records", "Records"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

        return []

    @staticmethod
    def _extract_total_count(response: dict[str, Any]) -> int | None:
        for path in (
            ("total",),
            ("totalCount",),
            ("TotalCount",),
            ("data", "total"),
            ("data", "totalCount"),
            ("data", "TotalCount"),
        ):
            value = _dig(response, *path)
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None

        return None

    @staticmethod
    def _raise_for_api_error(response: Any) -> None:
        if not isinstance(response, dict):
            return

        if response.get("result") is False:
            error = response.get("error")
            if isinstance(error, dict):
                error_code = error.get("code")
                message = error.get("msg") or error.get("message") or error.get("hint")
                raise RuntimeError(f"{error_code}: {message or error}")

            raise RuntimeError(response.get("msg") or response.get("message") or response)

        success_value = _first_value(response, "success", "Success", "succeed", "Succeed")
        if success_value is False:
            raise RuntimeError(response.get("message") or response.get("Message") or response)

        error_code = _first_value(response, "errcode", "errorCode", "ErrorCode", "code", "Code")
        if error_code not in (None, "", 0, "0", 200, "200"):
            message = _first_value(response, "errmsg", "errorMessage", "message", "Message", "msg")
            raise RuntimeError(f"{error_code}: {message or response}")


def build_standard_data_from_tplus_openapi() -> pd.DataFrame:
    client = TPlusOpenAPIClient()
    inventory_records = client.query_inventory()
    stock_records = client.query_current_stock()
    sales_df = client.query_recent_sale_delivery_sales()

    inventory_df = _build_inventory_master_df(inventory_records)
    stock_df = _build_current_stock_df(stock_records)

    inventory_summary_df = inventory_df.groupby("存货编码", as_index=False).agg(
        {
            "存货": "first",
        }
    )
    standard_df = stock_df.merge(
        inventory_summary_df,
        on="存货编码",
        how="left",
        suffixes=("_库存", ""),
    )

    if "存货_库存" in standard_df.columns:
        standard_df["存货"] = standard_df["存货"].fillna(standard_df["存货_库存"])
        standard_df = standard_df.drop(columns=["存货_库存"])

    standard_df = standard_df.merge(sales_df, on=["存货编码", "尺码"], how="left")
    standard_df["近7天销量"] = standard_df["近7天销量"].fillna(0)
    standard_df["日均销量"] = standard_df["日均销量"].fillna(0)
    standard_df["仓库编码"] = standard_df["仓库编码"].fillna("")
    standard_df["仓库"] = standard_df["仓库"].fillna("")
    standard_df["当前现存量"] = standard_df["当前现存量"].fillna(0)
    standard_df["当前可用量"] = standard_df["当前可用量"].fillna(0)
    standard_df["总部库存"] = 0

    return ensure_standard_columns(standard_df)


def test_inventory_query() -> dict[str, Any]:
    client = TPlusOpenAPIClient()
    url = f"{TPLUS_API_BASE_URL}{INVENTORY_QUERY_ENDPOINT}"
    headers = {
        "openToken": client.get_access_token(force_refresh=True),
        "appKey": TPLUS_APP_KEY,
        "appSecret": TPLUS_APP_SECRET,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = INVENTORY_QUERY_BODY

    print("[DEBUG-TPLUS-TEST] url:")
    print(url)
    print("[DEBUG-TPLUS-TEST] headers:")
    print(json.dumps(_mask_token_payload(headers), ensure_ascii=False, indent=2))
    print("[DEBUG-TPLUS-TEST] body:")
    print(json.dumps(body, ensure_ascii=False, indent=2))

    response = requests.post(url, headers=headers, json=body, timeout=30)
    try:
        response_json = response.json()
    except ValueError:
        response_json = {"raw_text": response.text}

    print("[DEBUG-TPLUS-TEST] status_code:")
    print(response.status_code)
    print("[DEBUG-TPLUS-TEST] response:")
    print(json.dumps(_mask_token_payload(response_json), ensure_ascii=False, indent=2))

    if isinstance(response_json, dict) and _is_exsv0011_response(response_json):
        _debug_tplus_curl(url, headers, {"json": body})

    return response_json


def test_find_sale_delivery_list() -> list[dict[str, Any]]:
    client = TPlusOpenAPIClient()
    rows = client.find_sale_delivery_list(page_index=1, page_size=10)
    print("[DEBUG-SALE-DELIVERY-TEST] parsed rows:")
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return rows


def _build_inventory_master_df(records: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for item in records:
        min_stock = _to_number(_field(item, "MinStockQuantity", "minStockQuantity", "SafetyStock", "safeStock"))
        rows.append(
            {
                "存货编码": clean_code(_field(item, "Code", "code", "InventoryCode", "inventoryCode", "InvCode")),
                "存货": str(_field(item, "Name", "name", "InventoryName", "inventoryName", "InvName") or ""),
                "尺码": clean_size(_field(item, "Specification", "specification", "Size", "size", "FreeItem0")),
                "近7天销量": min_stock,
                "日均销量": min_stock / SAFE_DAYS,
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("查询存货档案接口未返回有效数据")

    df["存货编码"] = df["存货编码"].apply(clean_code)
    df["尺码"] = df["尺码"].apply(clean_size)
    df["近7天销量"] = pd.to_numeric(df["近7天销量"], errors="coerce").fillna(0)
    df["日均销量"] = df["近7天销量"] / SAFE_DAYS

    return df.groupby(["存货编码", "存货", "尺码"], as_index=False).agg(
        {
            "近7天销量": "max",
            "日均销量": "max",
        }
    )


def _build_current_stock_df(records: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for item in records:
        existing_quantity = _to_number(
            _field(item, "ExistingQuantity", "existingQuantity", "Quantity", "quantity", "CurrentQuantity", "currentQuantity")
        )
        available_quantity = _to_number(
            _field(item, "AvailableQuantity", "availableQuantity", "AvailableQty", "availableQty")
        )
        rows.append(
            {
                "仓库编码": str(_field(item, "WarehouseCode", "warehouseCode", "WhCode", "whCode") or ""),
                "仓库": str(_field(item, "WarehouseName", "warehouseName", "WhName", "whName") or ""),
                "存货编码": clean_code(_field(item, "InventoryCode", "inventoryCode", "Code", "code", "InvCode")),
                "存货": str(_field(item, "InventoryName", "inventoryName", "Name", "name", "InvName") or ""),
                "尺码": clean_size(_field(item, "Specification", "specification", "Size", "size", "FreeItem0") or _first_dynamic_value(item)),
                "当前现存量": existing_quantity,
                "当前可用量": available_quantity or existing_quantity,
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=["仓库编码", "仓库", "存货编码", "存货", "尺码", "当前现存量", "当前可用量"]
        )

    df = pd.DataFrame(rows)
    if WARNING_WAREHOUSE_CODE:
        df = df[df["仓库编码"].astype(str).str.strip() == WARNING_WAREHOUSE_CODE].copy()
    if df.empty:
        return pd.DataFrame(
            columns=["仓库编码", "仓库", "存货编码", "存货", "尺码", "当前现存量", "当前可用量"]
        )
    df["当前现存量"] = pd.to_numeric(df["当前现存量"], errors="coerce").fillna(0)
    df["当前可用量"] = pd.to_numeric(df["当前可用量"], errors="coerce").fillna(0)

    return df.groupby(["存货编码", "尺码"], as_index=False).agg(
        {
            "当前现存量": "sum",
            "当前可用量": "sum",
            "仓库编码": "first",
            "仓库": "first",
            "存货": "first",
        }
    )


def _field(item: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in item:
            return item.get(name)

    for value in item.values():
        if isinstance(value, dict):
            nested = _field(value, *names)
            if nested not in (None, ""):
                return nested

    return None


def _to_number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _extract_voucher_code_date(voucher: dict[str, Any]) -> date | None:
    for key in ("code", "externalCode", "externalcode"):
        value = voucher.get(key)
        if not value:
            continue
        match = re.search(r"(20\d{2})[-/]?(\d{2})[-/]?(\d{2})", str(value))
        if not match:
            continue
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            continue
    return None


def _extract_sale_delivery_sales_rows(
    detail_response: dict[str, Any],
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    detail = detail_response.get("data") if isinstance(detail_response, dict) else None
    if not isinstance(detail, dict):
        return []

    voucher_date = _parse_date(detail.get("VoucherDate"))
    if voucher_date is None or voucher_date < start or voucher_date > end:
        return []

    header_warehouse_code = _extract_warehouse_code(detail)
    header_warehouse_name = _extract_warehouse_name(detail)
    rows: list[dict[str, Any]] = []
    for line in detail.get("SaleDeliveryDetails") or []:
        if not isinstance(line, dict):
            continue
        inventory_code = clean_code(_dig(line, "Inventory", "Code"))
        if not inventory_code:
            continue
        warehouse_code = _extract_warehouse_code(line) or header_warehouse_code
        warehouse_name = _extract_warehouse_name(line) or header_warehouse_name
        rows.append(
            {
                "存货编码": inventory_code,
                "尺码": clean_size(_first_dynamic_value(line)),
                "销售数量": _to_number(line.get("Quantity")),
                "仓库编码": warehouse_code,
                "仓库": warehouse_name,
            }
        )
    return rows


def _build_recent_sales_summary_df(rows: list[dict[str, Any]], days: int = SAFE_DAYS) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["存货编码", "尺码", "近7天销量", "日均销量"])

    sales_df = pd.DataFrame(rows)
    sales_df["销售数量"] = pd.to_numeric(sales_df["销售数量"], errors="coerce").fillna(0)

    if WARNING_WAREHOUSE_CODE and "仓库编码" in sales_df.columns:
        warehouse_codes = sales_df["仓库编码"].fillna("").astype(str).str.strip()
        if warehouse_codes.ne("").any():
            sales_df = sales_df[warehouse_codes == WARNING_WAREHOUSE_CODE].copy()

    if sales_df.empty:
        return pd.DataFrame(columns=["存货编码", "尺码", "近7天销量", "日均销量"])

    result = (
        sales_df.groupby(["存货编码", "尺码"], as_index=False)["销售数量"]
        .sum()
        .rename(columns={"销售数量": "近7天销量"})
    )
    result["近7天销量"] = result["近7天销量"].clip(lower=0)
    result["日均销量"] = result["近7天销量"] / days
    return result


def _extract_warehouse_code(item: dict[str, Any]) -> str:
    value = (
        _field(item, "WarehouseCode", "warehouseCode", "WhCode", "whCode")
        or _dig(item, "Warehouse", "Code")
        or _dig(item, "Warehouse", "code")
        or _dig(item, "WarehouseDTO", "Code")
        or _dig(item, "WarehouseDTO", "code")
    )
    return str(value or "").strip()


def _extract_warehouse_name(item: dict[str, Any]) -> str:
    value = (
        _field(item, "WarehouseName", "warehouseName", "WhName", "whName")
        or _dig(item, "Warehouse", "Name")
        or _dig(item, "Warehouse", "name")
        or _dig(item, "WarehouseDTO", "Name")
        or _dig(item, "WarehouseDTO", "name")
    )
    return str(value or "").strip()


def _read_recent_sales_cache(cache_key: dict[str, Any]) -> pd.DataFrame | None:
    if not os.path.exists(TPLUS_RECENT_SALES_CACHE_FILE):
        return None

    try:
        with open(TPLUS_RECENT_SALES_CACHE_FILE, "r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None
    if payload.get("cache_key") != cache_key:
        return None

    cached_at = float(payload.get("cached_at") or 0)
    if cached_at + TPLUS_RECENT_SALES_CACHE_TTL_SECONDS <= time.time():
        return None

    rows = payload.get("rows")
    if not isinstance(rows, list):
        return None

    return pd.DataFrame(rows, columns=["存货编码", "尺码", "近7天销量", "日均销量"])


def _write_recent_sales_cache(cache_key: dict[str, Any], sales_df: pd.DataFrame) -> None:
    os.makedirs(os.path.dirname(TPLUS_RECENT_SALES_CACHE_FILE), exist_ok=True)
    payload = {
        "cache_key": cache_key,
        "cached_at": time.time(),
        "rows": sales_df.to_dict(orient="records"),
    }
    with open(TPLUS_RECENT_SALES_CACHE_FILE, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def _first_dynamic_value(item: dict[str, Any]) -> Any:
    values = item.get("DynamicPropertyValues") or item.get("dynamicPropertyValues")
    if isinstance(values, list) and values:
        return values[0]
    return None


def _dig(payload: dict[str, Any], *path: str) -> Any:
    value: Any = payload
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)

    return value


def _normalize_token_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "access_token": payload.get("access_token") or payload.get("accessToken"),
        "refresh_token": payload.get("refresh_token") or payload.get("refreshToken"),
        "expires_in": payload.get("expires_in") or payload.get("expiresIn"),
        "refresh_expires_in": payload.get("refresh_expires_in") or payload.get("refreshExpiresIn"),
        "org_id": payload.get("org_id") or payload.get("orgId"),
        "user_id": payload.get("user_id") or payload.get("userId"),
        "app_name": payload.get("app_name") or payload.get("appName"),
        "scope": payload.get("scope"),
        "user_auth_permanent_code": payload.get("user_auth_permanent_code")
        or payload.get("userAuthPermanentCode"),
        "sid": payload.get("sid"),
    }


def _debug_generate_token_response(response: dict[str, Any]) -> None:
    watched_keys = {
        "orgId",
        "org_id",
        "tenantId",
        "tenant_id",
        "accountId",
        "account_id",
        "orgName",
        "org_name",
        "accountName",
        "account_name",
        "orgAccount",
        "org_account",
        "bookCode",
        "book_code",
    }
    matches = _find_debug_fields(response, watched_keys)
    print("[DEBUG-TPLUS-TOKEN] generateToken full response:")
    print(json.dumps(_mask_token_payload(response), ensure_ascii=False, indent=2))
    print("[DEBUG-TPLUS-TOKEN] org/account fields:")
    if matches:
        for path, value in matches:
            print(f"[DEBUG-TPLUS-TOKEN] {path}={value}")
    else:
        print("[DEBUG-TPLUS-TOKEN] no org/account fields found")


def _debug_tplus_business_request(url: str, headers: dict[str, str], request_kwargs: dict[str, Any]) -> None:
    body = request_kwargs.get("json")
    if body is None:
        body = request_kwargs.get("data")
    print("[DEBUG-TPLUS-REQUEST] url:")
    print(url)
    print("[DEBUG-TPLUS-REQUEST] headers:")
    print(json.dumps(_mask_token_payload(headers), ensure_ascii=False, indent=2))
    print("[DEBUG-TPLUS-REQUEST] body:")
    print(json.dumps(_mask_token_payload(body), ensure_ascii=False, indent=2))


def _debug_tplus_business_response(status_code: int, response_json: dict[str, Any]) -> None:
    print("[DEBUG-TPLUS-RESPONSE] status_code:")
    print(status_code)
    print("[DEBUG-TPLUS-RESPONSE] json:")
    print(json.dumps(_mask_token_payload(response_json), ensure_ascii=False, indent=2))


def _debug_tplus_business_response_from_error(response: requests.Response) -> None:
    try:
        response_json = response.json()
    except ValueError:
        response_json = {"raw_text": response.text}
    _debug_tplus_business_response(response.status_code, response_json)


def _debug_sale_delivery_request(url: str, headers: dict[str, str], body: dict[str, Any]) -> None:
    print("[DEBUG-SALE-DELIVERY] url:")
    print(url)
    print("[DEBUG-SALE-DELIVERY] headers:")
    print(json.dumps(_mask_secret_headers(headers), ensure_ascii=False, indent=2))
    print("[DEBUG-SALE-DELIVERY] body:")
    print(json.dumps(body, ensure_ascii=False, indent=2))


def _debug_sale_delivery_response(
    status_code: int,
    response_json: Any,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
) -> None:
    print("[DEBUG-SALE-DELIVERY] status_code:")
    print(status_code)
    print("[DEBUG-SALE-DELIVERY] response:")
    print(json.dumps(response_json, ensure_ascii=False, indent=2))
    if _is_api_error(response_json):
        print("[DEBUG-SALE-DELIVERY] curl:")
        print(_build_masked_curl(url, headers, body))


def _build_masked_curl(url: str, headers: dict[str, str], body: dict[str, Any]) -> str:
    parts = ["curl -X POST", f'"{url}"']
    for key, value in _mask_secret_headers(headers).items():
        parts.append(f'-H "{key}: {value}"')
    parts.append(f"--data '{json.dumps(body, ensure_ascii=False)}'")
    return " \\\n  ".join(parts)


def _is_api_error(response_json: Any) -> bool:
    if isinstance(response_json, list):
        return False
    if not isinstance(response_json, dict):
        return False
    code = response_json.get("code")
    if code is None:
        code = _dig(response_json, "data", "Code")
    return str(code) not in {"0", "200", "", "None"}


def _mask_secret_headers(headers: dict[str, str]) -> dict[str, str]:
    masked: dict[str, str] = {}
    for key, value in headers.items():
        if key == "openToken":
            masked[key] = _mask_secret(str(value), head=8, tail=4)
        elif key == "appSecret":
            masked[key] = _mask_secret(str(value), head=4, tail=4)
        else:
            masked[key] = value
    return masked


def _debug_tplus_curl(url: str, headers: dict[str, str], request_kwargs: dict[str, Any]) -> None:
    body = request_kwargs.get("json")
    if body is None:
        body = request_kwargs.get("data")
    safe_headers = _mask_token_payload(headers)
    body_text = json.dumps(body, ensure_ascii=False)
    parts = ["curl -X POST", f'"{url}"']
    for key, value in safe_headers.items():
        parts.append(f'-H "{key}: {value}"')
    parts.append(f"--data '{body_text}'")
    print("[DEBUG-TPLUS-CURL] equivalent request with secrets masked:")
    print(" \\\n  ".join(parts))


def _is_exsv0011_response(response_json: Any) -> bool:
    if not isinstance(response_json, dict):
        return False
    code = response_json.get("code") or _dig(response_json, "data", "Code")
    return str(code).upper() == "EXSV0011"


def _format_tplus_request_error(error: Exception | None, endpoint: str) -> str:
    message = f"调用畅捷通 T+ OpenAPI 失败：{error}；当前接口路径：{endpoint}。"

    if isinstance(error, requests.Timeout):
        return (
            message
            +
            f"接口在 {TPLUS_REQUEST_TIMEOUT} 秒内没有返回响应。请先确认服务器能访问 openapi.chanjet.com，"
            "再根据现场网络和账套数据量调大 TPLUS_REQUEST_TIMEOUT，或调小 TPLUS_QUERY_PAGE_SIZE 后重试。"
        )

    if error and "EXSV0011" in str(error).upper():
        return (
            message
            +
            "错误码是 EXSV0011，请在畅捷通开放平台 API 文档/应用权限中确认真实服务名称，"
            "并通过 TPLUS_INVENTORY_QUERY_ENDPOINT 或 TPLUS_CURRENT_STOCK_QUERY_ENDPOINT 配置。"
        )

    return (
        message
        +
        "如果错误码是 EXSV0011，请在畅捷通开放平台 API 文档/应用权限中确认真实服务名称，"
        "并通过 TPLUS_INVENTORY_QUERY_ENDPOINT 或 TPLUS_CURRENT_STOCK_QUERY_ENDPOINT 配置。"
    )


def _mask_token_payload(value: Any) -> Any:
    secret_keys = {
        "access_token",
        "accessToken",
        "refresh_token",
        "refreshToken",
        "token",
        "openToken",
        "appSecret",
        "Authorization",
        "authorization",
    }
    if isinstance(value, dict):
        return {
            key: _mask_secret(str(item)) if key in secret_keys else _mask_token_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_mask_token_payload(item) for item in value]
    return value


def _mask_secret(value: str, head: int = 6, tail: int = 4) -> str:
    if len(value) <= head + tail:
        return "***"
    return f"{value[:head]}...{value[-tail:]}"


def _parse_columns_rows_response(response: Any) -> list[dict[str, Any]]:
    if isinstance(response, list):
        return [item for item in response if isinstance(item, dict)]

    if not isinstance(response, dict):
        return []

    data = response.get("data")
    if not isinstance(data, dict):
        return []

    columns = data.get("Columns") or data.get("columns") or []
    rows = data.get("Rows") or data.get("rows") or []
    if not isinstance(columns, list) or not isinstance(rows, list):
        return []

    parsed_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, list):
            continue
        parsed_rows.append({str(columns[idx]): row[idx] if idx < len(row) else None for idx in range(len(columns))})

    return parsed_rows


def _find_debug_fields(value: Any, watched_keys: set[str], prefix: str = "") -> list[tuple[str, Any]]:
    matches: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else key
            if key in watched_keys:
                matches.append((path, item))
            matches.extend(_find_debug_fields(item, watched_keys, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            matches.extend(_find_debug_fields(item, watched_keys, f"{prefix}[{index}]"))
    return matches


def _extract_app_ticket(payload: dict[str, Any]) -> str | None:
    for key in ("appTicket", "app_ticket", "ticket", "app_ticket_value"):
        value = payload.get(key)
        if value:
            return str(value)

    for key in ("value", "data", "event", "payload", "bizContent"):
        value = payload.get(key)
        if isinstance(value, dict):
            app_ticket = _extract_app_ticket(value)
            if app_ticket:
                return app_ticket

    return None


def _first_value(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload.get(key)

    return None
