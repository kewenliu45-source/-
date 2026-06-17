import json
import logging
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
    TPLUS_DEBUG,
    TPLUS_INVENTORY_QUERY_ENDPOINT,
    TPLUS_CURRENT_STOCK_QUERY_ENDPOINT,
    TPLUS_RECENT_SALES_CACHE_FILE,
    TPLUS_RECENT_SALES_CACHE_TTL_SECONDS,
    TPLUS_TRANSIT_WAREHOUSE_CODES,
    TPLUS_TRANSIT_WAREHOUSE_NAMES,
    WARNING_WAREHOUSE_CODE,
    APP_SECRET,
    TPLUS_TOKEN_CACHE_FILE,
    TPLUS_TOKEN_REFRESH_SKEW_SECONDS,
)
from app.data_sources.base import ensure_standard_columns
from app.data_sources.excel_source import clean_code, clean_size
from app.data_sources.base import _normalize_warehouse_code


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
            # token 还没过期但无 appTicket 时，直接用缓存 token，不尝试刷新
            if not force_refresh and self._cached_access_token_not_expired(cached_token):
                if not self._read_latest_app_ticket():
                    return str(cached_token["access_token"])

            try:
                token_payload = self._generate_self_built_access_token()
                token = token_payload.get("access_token")
                if not token:
                    raise RuntimeError(f"自建应用获取 token 成功但响应中未找到 accessToken：{token_payload}")
                return str(token)
            except RuntimeError:
                if not force_refresh and self._cached_access_token_not_expired(cached_token):
                    logging.warning(
                        "T+ self_built 刷新 token 失败，但缓存 accessToken 尚未过期，继续使用缓存 token"
                    )
                    return str(cached_token["access_token"])
                raise

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
            raise RuntimeError(
                "T+ accessToken 已过期且未找到可用 appTicket，请检查畅捷通消息回调配置。"
            )

        return self.generate_self_built_token(app_ticket, TPLUS_CERTIFICATE)

    def query_inventory(self) -> list[dict[str, Any]]:
        return self._query_all_pages_with_param(INVENTORY_QUERY_ENDPOINT, INVENTORY_QUERY_BODY)

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
        max_detail_workers: int = 16,
        param_dic: dict[str, Any] | None = None,
        end_date: date | None = None,
        force_refresh: bool = False,
        column_name: str = "近7天销量",
    ) -> pd.DataFrame:
        end = end_date or date.today()
        start = end - timedelta(days=days - 1)
        cache_key = {
            "version": 4,
            "days": days,
            "end_date": end.isoformat(),
            "column_name": column_name,
            "param_dic": param_dic or {},
        }
        if not force_refresh:
            cached_sales_df = _read_recent_sales_cache(cache_key)
            if cached_sales_df is not None:
                print(f"[T+]   {column_name}命中缓存，{len(cached_sales_df)} 条")
                return cached_sales_df

        print(f"[T+]   {column_name}缓存未命中，开始查询销货单列表...")
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
        print(f"[T+]   {column_name}找到 {len(candidate_vouchers)} 张销货单，开始查询明细...")

        rows: list[dict[str, Any]] = []
        worker_count = max(1, min(max_detail_workers, len(candidate_vouchers) or 1))
        done_count = 0
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
                done_count += 1
                if done_count % 10 == 0 or done_count == len(candidate_vouchers):
                    print(f"[T+]   {column_name}明细进度: {done_count}/{len(candidate_vouchers)}")
                try:
                    detail_response = future.result()
                except Exception as exc:
                    print(f"[DEBUG-SALE-DELIVERY] skip detail error: {exc}")
                    continue
                rows.extend(_extract_sale_delivery_sales_rows(detail_response, start, end))

        if not rows:
            empty_result = pd.DataFrame(columns=["存货编码", "尺码", column_name, "日均销量"])
            _write_recent_sales_cache(cache_key, empty_result)
            return empty_result

        result = _build_recent_sales_summary_df(rows, days, column_name=column_name)
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

    def _query_all_pages_with_param(
        self,
        endpoint: str,
        base_body: dict[str, Any],
        max_pages: int = 50,
    ) -> list[dict[str, Any]]:
        """分页查询，PageIndex/PageSize 放在 param 内部。

        T+ inventory/Query 等接口要求分页参数在 param 内，
        与 SaleDelivery 系列接口（顶层 pageIndex/pageSize）不同。

        通过去重检测防止 API 不支持真正分页时的死循环。
        """
        records: list[dict[str, Any]] = []
        seen_codes: set[str] = set()
        page_index = 1

        while page_index <= max_pages:
            body = json.loads(json.dumps(base_body))  # deep copy
            param = body.setdefault("param", {})
            param["PageIndex"] = page_index
            param["PageSize"] = TPLUS_QUERY_PAGE_SIZE

            response = self._request("POST", endpoint, json=body)
            page_records = self._extract_records(response)

            # 去重：检测 API 是否返回了重复数据（不支持真正分页）
            new_records = []
            for rec in page_records:
                code = str(rec.get("Code") or rec.get("code") or rec.get("InventoryCode") or id(rec))
                if code not in seen_codes:
                    seen_codes.add(code)
                    new_records.append(rec)

            records.extend(new_records)
            print(f"[T+]   分页查询 {endpoint} 第{page_index}页: +{len(new_records)} 条(去重), 累计 {len(records)} 条")

            # 如果本页全部是重复数据，说明已拿完或 API 不支持分页
            if not new_records:
                print(f"[T+]   第{page_index}页全部重复，停止翻页")
                break

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
        debug_business_request = TPLUS_DEBUG and endpoint in {
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

    @staticmethod
    def _cached_access_token_not_expired(payload: dict[str, Any] | None) -> bool:
        """Check if the cached access token has not truly expired (ignoring refresh skew)."""
        if not payload:
            return False

        token = payload.get("access_token")
        expires_at = float(payload.get("access_token_expires_at") or payload.get("expires_at") or 0)
        return bool(token) and expires_at > time.time()

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


def build_standard_data_from_tplus_openapi(
    hq_df: pd.DataFrame | None = None,
    transit_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """从 T+ OpenAPI 获取库存和销售数据，复用 build_standard_data_from_frames 合并。

    并行查询：存货档案、当前库存、7天销售、90天销售。
    以存货档案为主表，确保所有存货（包括库存为0的）都出现在结果中。

    Args:
        hq_df: 总部库存数据（可选，来自上传的 Excel）
        transit_df: 在途库存数据（可选，来自上传的 Excel）
    """
    from concurrent.futures import ThreadPoolExecutor
    from app.data_sources.base import build_standard_data_from_frames

    client = TPlusOpenAPIClient()

    # 预获取 token，避免 4 个并行线程各自刷新
    print("[T+] 正在获取访问令牌...")
    try:
        client.get_access_token()
        print("[T+] [OK] 令牌获取成功")
    except Exception as exc:
        logging.warning("预获取 T+ token 失败，将在各线程中重试: %s", exc)

    inventory_records = None
    stock_records = None
    sales_df = None
    sales_90_df = None

    def fetch_inventory():
        nonlocal inventory_records
        print("[T+] 开始查询存货档案...")
        inventory_records = client.query_inventory()
        print(f"[T+] [OK] 存货档案: {len(inventory_records)} 条")

    def fetch_stock():
        nonlocal stock_records
        print("[T+] 开始查询当前库存...")
        stock_records = client.query_current_stock()
        print(f"[T+] [OK] 当前库存: {len(stock_records)} 条")

    def fetch_sales_7d():
        nonlocal sales_df
        print("[T+] 开始查询近7天销量...")
        sales_df = client.query_recent_sale_delivery_sales()
        print(f"[T+] [OK] 近7天销量: {len(sales_df) if sales_df is not None and not sales_df.empty else 0} 条")

    def fetch_sales_90d():
        nonlocal sales_90_df
        print("[T+] 开始查询近90天销量...")
        try:
            sales_90_df = query_90day_sales()
            print(f"[T+] [OK] 近90天销量: {len(sales_90_df) if sales_90_df is not None and not sales_90_df.empty else 0} 条")
        except Exception as exc:
            logging.warning("近90天销量查询失败，降级为0: %s", exc)
            print(f"[T+] [FAIL] 近90天销量查询失败: {exc}")

    print("[T+] 并行查询存货/库存/7天销量/90天销量...")
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda fn: fn(), [fetch_inventory, fetch_stock, fetch_sales_7d, fetch_sales_90d]))
    print("[T+] [OK] 全部数据查询完成")

    # 存货档案：所有存货（含库存为0的）
    inventory_master_df = _build_inventory_master_df(inventory_records)
    # 当前库存：只有有库存记录的存货
    stock_df = _build_current_stock_df(stock_records)

    # 用 currentStock 的数据补全存货档案
    # （inventory/Query 可能只返回部分 SKU，且不含尺码；currentStock 有更完整的数据）
    stock_name_map: dict[str, str] = {}
    for rec in stock_records:
        code = clean_code(_field(rec, "InventoryCode", "inventoryCode", "Code", "code", "InvCode"))
        name = str(_field(rec, "InventoryName", "inventoryName", "Name", "name", "InvName") or "")
        if code and name and code not in stock_name_map:
            stock_name_map[code] = name

    # 补全 inventory_master_df 中名称为空的行
    if stock_name_map:
        inv_missing_name = inventory_master_df["存货"] == ""
        if inv_missing_name.any():
            inventory_master_df.loc[inv_missing_name, "存货"] = (
                inventory_master_df.loc[inv_missing_name, "存货编码"].map(stock_name_map).fillna("")
            )

    # 用 currentStock 补入缺失的 存货编码+尺码 组合
    # （inventory_master_df 可能缺少尺码维度，stock 有完整的 SKU+尺码 数据）
    existing_keys = set(zip(inventory_master_df["存货编码"], inventory_master_df["尺码"]))
    extra_rows = []
    for rec in stock_records:
        code = clean_code(_field(rec, "InventoryCode", "inventoryCode", "Code", "code", "InvCode"))
        size = clean_size(
            _first_dynamic_value(rec)
            or _field(rec, "Specification", "specification", "Size", "size", "FreeItem0")
        )
        if code and (code, size) not in existing_keys:
            existing_keys.add((code, size))
            name = stock_name_map.get(code, "")
            extra_rows.append({"存货编码": code, "存货": name, "尺码": size})
    if extra_rows:
        extra_df = pd.DataFrame(extra_rows)
        inventory_master_df = pd.concat([inventory_master_df, extra_df], ignore_index=True)
        print(f"[T+] 从 currentStock 补入 {len(extra_rows)} 个缺失的 SKU+尺码 组合")

    # 用库存记录中的 Specification↔DynamicPropertyValues 映射修正存货档案的尺码
    size_alias = _build_tplus_size_alias_map(stock_records)
    if size_alias:
        inventory_master_df["尺码"] = inventory_master_df.apply(
            lambda row: size_alias.get((row["存货编码"], row["尺码"]), row["尺码"]),
            axis=1,
        )
        inventory_master_df = inventory_master_df.drop_duplicates(subset=["存货编码", "尺码"])

    # 以 sales_df 为主表 LEFT JOIN stock（保持销货单的尺码格式，确保销售数据匹配正确）
    if sales_df is None or sales_df.empty:
        sales_df = inventory_master_df[["存货编码", "存货", "尺码"]].copy()
        sales_df["近7天销量"] = 0
        sales_df["日均销量"] = 0.0

    standard_df = sales_df.merge(
        stock_df[["存货编码", "尺码", "存货", "仓库编码", "仓库", "当前现存量", "当前可用量"]],
        on=["存货编码", "尺码"],
        how="left",
        suffixes=("", "_库存"),
    )
    # 存货名称补全：优先用 sales 的，缺失时用 stock 的
    if "存货_库存" in standard_df.columns:
        if "存货" in standard_df.columns:
            standard_df["存货"] = standard_df["存货"].fillna(standard_df["存货_库存"])
        else:
            standard_df["存货"] = standard_df["存货_库存"]
        standard_df = standard_df.drop(columns=["存货_库存"])
    if "存货" not in standard_df.columns:
        standard_df["存货"] = ""
    # 用 stock_name_map 补全仍然缺失的存货名称
    standard_df["存货"] = standard_df["存货"].fillna("")
    still_empty = standard_df["存货"] == ""
    if still_empty.any() and stock_name_map:
        standard_df.loc[still_empty, "存货"] = (
            standard_df.loc[still_empty, "存货编码"].map(stock_name_map).fillna("")
        )
    standard_df["仓库编码"] = standard_df["仓库编码"].fillna(WARNING_WAREHOUSE_CODE)
    standard_df["仓库"] = standard_df["仓库"].fillna("")
    standard_df["当前现存量"] = standard_df["当前现存量"].fillna(0)
    standard_df["当前可用量"] = standard_df["当前可用量"].fillna(0)

    # 补入存货档案中不在销售+库存结果里的存货（库存为0且无销售记录）
    existing_keys = set(zip(standard_df["存货编码"], standard_df["尺码"]))
    master_keys = inventory_master_df[["存货编码", "尺码"]].apply(tuple, axis=1)
    extra_master = inventory_master_df[~master_keys.isin(existing_keys)].copy()
    if not extra_master.empty:
        extra_master["仓库编码"] = WARNING_WAREHOUSE_CODE
        extra_master["仓库"] = ""
        extra_master["当前现存量"] = 0
        extra_master["当前可用量"] = 0
        extra_master["在途仓"] = ""
        extra_master["近7天销量"] = 0
        extra_master["日均销量"] = 0
        keep_cols = [c for c in standard_df.columns if c in extra_master.columns]
        extra_master = extra_master[keep_cols]
        standard_df = pd.concat([standard_df, extra_master], ignore_index=True)

    # T+ 在途仓数量：从 currentStock/Query 的仓库维度提取在途仓库存数量
    tplus_transit_df = _build_tplus_transit_from_stock_df(stock_records)

    # 合并 T+ 在途仓数量和人工导入的 transit_df
    # 在途仓 来源：T+ currentStock 在途仓 ExistingQuantity
    # 在途（未发货） 来源：人工 transit_df
    if transit_df is not None and not transit_df.empty:
        # 人工 transit_df 有在途（未发货）数量 → 合并 T+ 在途仓数量
        if not tplus_transit_df.empty:
            # 合并：T+ 在途仓 + 人工 在途（未发货）
            transit_df = transit_df.copy()
            transit_df = transit_df.merge(
                tplus_transit_df[["存货编码", "尺码", "在途仓"]],
                on=["存货编码", "尺码"],
                how="outer",
                suffixes=("", "_tplus"),
            )
            # 在途仓取 T+ 的值（如果有），保留人工 transit_df 的在途（未发货）
            if "在途仓_tplus" in transit_df.columns:
                transit_df["在途仓"] = transit_df["在途仓_tplus"].fillna(
                    transit_df.get("在途仓", 0)
                )
                transit_df = transit_df.drop(columns=["在途仓_tplus"])
    else:
        # 未传人工 transit_df → 只用 T+ 在途仓数量
        transit_df = tplus_transit_df if not tplus_transit_df.empty else None

    # 用 build_standard_data_from_frames 处理 hq/transit/90day 合并（不传 sales_df，已预合并）
    return build_standard_data_from_frames(
        inventory_df=standard_df,
        sales_df=None,
        hq_df=hq_df,
        transit_df=transit_df,
        sales_90_df=sales_90_df,
        already_cleaned=True,
    )


def query_tplus_transit_stock() -> pd.DataFrame:
    """查询 T+ 在途库存数据。

    当前 T+ 在途接口尚未接入，返回空表降级。
    接入真实接口后替换此函数实现即可。
    """
    logging.warning("T+ 在途接口尚未接入，本次在途仓为空")
    return pd.DataFrame(columns=["存货编码", "尺码", "在途仓", "在途（未发货）"])


def _build_tplus_transit_df(records: list[dict[str, Any]]) -> pd.DataFrame:
    """将 T+ 在途 API 原始记录标准化为 DataFrame。

    Args:
        records: T+ 在途 API 返回的原始记录列表

    Returns:
        列: 存货编码, 尺码, 在途仓, 在途（未发货）
    """
    if not records:
        return pd.DataFrame(columns=["存货编码", "尺码", "在途仓", "在途（未发货）"])

    rows = []
    for item in records:
        code = clean_code(_field(item, "InventoryCode", "inventoryCode", "Code", "code", "InvCode"))
        size = clean_size(
            _first_dynamic_value(item)
            or _field(item, "Specification", "specification", "Size", "size", "FreeItem0")
        )
        warehouse = str(
            _field(item, "TransitWarehouse", "transitWarehouse", "WarehouseName", "warehouseName", "WhName", "whName") or ""
        )
        quantity = _to_number(_field(item, "Quantity", "quantity", "TransitQuantity", "transitQuantity", "Qty", "qty"))
        if code and quantity > 0:
            rows.append({
                "存货编码": code,
                "尺码": size,
                "在途仓": warehouse,
                "在途（未发货）": quantity,
            })

    if not rows:
        return pd.DataFrame(columns=["存货编码", "尺码", "在途仓", "在途（未发货）"])

    df = pd.DataFrame(rows)
    df["在途（未发货）"] = pd.to_numeric(df["在途（未发货）"], errors="coerce").fillna(0)
    df = df[df["在途（未发货）"] > 0]

    # 按 存货编码+尺码 聚合：数量求和，在途仓去重拼接
    agg_df = (
        df.groupby(["存货编码", "尺码"], as_index=False)
        .agg({
            "在途（未发货）": "sum",
            "在途仓": lambda x: ",".join(sorted(set(v for v in x if v))),
        })
    )
    return agg_df


def query_90day_sales() -> pd.DataFrame:
    """查询近90天销售数据，返回列: 存货编码, 尺码, 近90天销量。

    不返回日均销量，避免与近7天日均销量混淆。
    返回的 DataFrame 可直接传给 build_standard_data_from_frames(sales_90_df=...)。
    """
    client = TPlusOpenAPIClient()
    df = client.query_recent_sale_delivery_sales(
        days=90,
        column_name="近90天销量",
        force_refresh=False,
    )
    # 只保留标准合并需要的列，去掉日均销量
    keep_cols = [c for c in ["存货编码", "尺码", "近90天销量"] if c in df.columns]
    return df[keep_cols]


def _diagnose_query_response(
    label: str,
    endpoint: str,
    request_body: dict[str, Any],
    response: Any,
    record_fields: list[str],
) -> dict[str, Any]:
    """诊断单个 T+ Query 接口的响应结构。

    兼容 response 为 list 或 dict 两种情况。

    Returns:
        包含 endpoint, body, response_keys, records_count, 分页字段 等的字典
    """
    print(f"\n[DIAG] {label}")
    print(f"[DIAG] endpoint: {endpoint}")
    print(f"[DIAG] request body: {json.dumps(request_body, ensure_ascii=False)}")

    records: list[dict[str, Any]] = []
    pagination: dict[str, Any] = {}

    if isinstance(response, list):
        # response 直接是记录列表，无分页信息
        print(f"[DIAG] response type: list, len={len(response)}")
        records = [item for item in response if isinstance(item, dict)]

    elif isinstance(response, dict):
        print(f"[DIAG] response keys: {list(response.keys())}")
        data = response.get("data")
        if isinstance(data, dict):
            print(f"[DIAG] data keys: {list(data.keys())}")
            for key in ("TotalCount", "TotalPageNum", "pageIndex", "pageSize", "total", "totalCount"):
                if key in data:
                    pagination[key] = data[key]
                    print(f"[DIAG] data.{key} = {data[key]}")
            # records 可能在 data.rows / data.Rows / data.records 等
            for key in ("rows", "Rows", "items", "Items", "list", "List", "records", "Records"):
                val = data.get(key)
                if isinstance(val, list):
                    records = [item for item in val if isinstance(item, dict)]
                    print(f"[DIAG] data.{key} is list, len={len(records)}")
                    break
        elif isinstance(data, list):
            print(f"[DIAG] data is list, len={len(data)}")
            records = [item for item in data if isinstance(item, dict)]

    else:
        print(f"[DIAG] response type: {type(response)}")

    print(f"[DIAG] extracted records count: {len(records)}")
    if records:
        print(f"[DIAG] first 3 records:")
        for i, rec in enumerate(records[:3]):
            parts = []
            for f in record_fields:
                parts.append(f"{f}={rec.get(f)}")
            print(f"  [{i}] {', '.join(parts)}")

    result: dict[str, Any] = {
        "endpoint": endpoint,
        "body": request_body,
        "response_type": type(response).__name__,
        "response_keys": list(response.keys()) if isinstance(response, dict) else None,
        "records_count": len(records),
        "data_keys": list(response.get("data", {}).keys()) if isinstance(response, dict) and isinstance(response.get("data"), dict) else None,
    }
    result.update(pagination)
    return result, records


def test_tplus_inventory_and_stock_paging() -> dict[str, Any]:
    """诊断函数：探测 inventory/Query 和 currentStock/Query 的分页情况和仓库分布。

    只读不改，不接入主流程。用于排查：
    1. 接口是否只返回了第一页（约200条）
    2. currentStock 的仓库分布和在途仓命中情况
    3. response 是 list 还是 dict

    Returns:
        诊断结果字典
    """
    from app.config import TPLUS_TRANSIT_WAREHOUSE_CODES, TPLUS_TRANSIT_WAREHOUSE_NAMES

    client = TPlusOpenAPIClient()
    results: dict[str, Any] = {}

    # ========== 1. inventory/Query 诊断 ==========
    print("\n" + "=" * 60)
    print("[DIAG] inventory/Query 诊断")
    print("=" * 60)

    inv_body = dict(INVENTORY_QUERY_BODY)
    inv_response = client._request("POST", INVENTORY_QUERY_ENDPOINT, json=inv_body)
    inv_info, inv_records = _diagnose_query_response(
        "inventory/Query", INVENTORY_QUERY_ENDPOINT, inv_body, inv_response,
        record_fields=["Code", "Name", "Specification", "DynamicPropertyValues"],
    )
    results["inventory"] = inv_info

    # ========== 2. currentStock/Query 诊断 ==========
    print("\n" + "=" * 60)
    print("[DIAG] currentStock/Query 诊断")
    print("=" * 60)

    stock_body = dict(CURRENT_STOCK_QUERY_BODY)
    stock_response = client._request("POST", CURRENT_STOCK_QUERY_ENDPOINT, json=stock_body)
    stock_info, stock_records = _diagnose_query_response(
        "currentStock/Query", CURRENT_STOCK_QUERY_ENDPOINT, stock_body, stock_response,
        record_fields=["WarehouseCode", "WarehouseName", "InventoryCode", "Specification",
                        "DynamicPropertyValues", "ExistingQuantity"],
    )
    results["stock"] = stock_info

    # ========== 3. currentStock 仓库分布统计 ==========
    print("\n" + "=" * 60)
    print("[DIAG] currentStock 仓库分布统计")
    print("=" * 60)

    wh_name_counts: dict[str, int] = {}
    wh_code_counts: dict[str, int] = {}
    for rec in stock_records:
        wh_name = str(rec.get("WarehouseName") or rec.get("warehouseName") or rec.get("WhName") or "").strip()
        wh_code = str(rec.get("WarehouseCode") or rec.get("warehouseCode") or rec.get("WhCode") or "").strip()
        wh_name_counts[wh_name] = wh_name_counts.get(wh_name, 0) + 1
        wh_code_counts[wh_code] = wh_code_counts.get(wh_code, 0) + 1

    print(f"[DIAG] total records: {len(stock_records)}")
    print(f"[DIAG] unique WarehouseName count: {len(wh_name_counts)}")
    print(f"[DIAG] WarehouseName distribution:")
    for name, count in sorted(wh_name_counts.items(), key=lambda x: -x[1]):
        print(f"  '{name}': {count}")

    print(f"[DIAG] unique WarehouseCode count: {len(wh_code_counts)}")
    print(f"[DIAG] WarehouseCode distribution:")
    for code, count in sorted(wh_code_counts.items(), key=lambda x: -x[1]):
        print(f"  '{code}': {count}")

    # 在途仓命中统计
    transit_by_name = 0
    transit_by_code = 0
    for rec in stock_records:
        wh_name = str(rec.get("WarehouseName") or rec.get("warehouseName") or rec.get("WhName") or "").strip()
        wh_code = str(rec.get("WarehouseCode") or rec.get("warehouseCode") or rec.get("WhCode") or "").strip()

        for t_name in TPLUS_TRANSIT_WAREHOUSE_NAMES:
            if t_name and t_name in wh_name:
                transit_by_name += 1
                break

        if TPLUS_TRANSIT_WAREHOUSE_CODES:
            from app.data_sources.base import _normalize_warehouse_code
            norm_code = _normalize_warehouse_code(wh_code)
            for t_code in TPLUS_TRANSIT_WAREHOUSE_CODES:
                if t_code and _normalize_warehouse_code(t_code) == norm_code:
                    transit_by_code += 1
                    break

    has_transit_name = any(
        any(t_name in str(rec.get("WarehouseName") or rec.get("warehouseName") or rec.get("WhName") or "")
            for t_name in TPLUS_TRANSIT_WAREHOUSE_NAMES)
        for rec in stock_records
    )

    print(f"[DIAG] TPLUS_TRANSIT_WAREHOUSE_NAMES = {TPLUS_TRANSIT_WAREHOUSE_NAMES}")
    print(f"[DIAG] TPLUS_TRANSIT_WAREHOUSE_CODES = {TPLUS_TRANSIT_WAREHOUSE_CODES}")
    print(f"[DIAG] records matching transit names: {transit_by_name}")
    print(f"[DIAG] records matching transit codes: {transit_by_code}")
    print(f"[DIAG] any record with '在途' in WarehouseName: {has_transit_name}")

    results["stock_distribution"] = {
        "total_records": len(stock_records),
        "unique_warehouse_names": len(wh_name_counts),
        "warehouse_name_counts": wh_name_counts,
        "unique_warehouse_codes": len(wh_code_counts),
        "warehouse_code_counts": wh_code_counts,
        "transit_match_by_name": transit_by_name,
        "transit_match_by_code": transit_by_code,
        "has_transit_in_name": has_transit_name,
    }

    # ========== 4. 构建 DataFrame 各阶段数量 ==========
    print("\n" + "=" * 60)
    print("[DIAG] DataFrame 构建各阶段数量")
    print("=" * 60)

    inv_master_rows = 0
    stock_df_rows = 0
    transit_df_rows = 0

    try:
        inventory_master_df = _build_inventory_master_df(inv_records)
        inv_master_rows = len(inventory_master_df)
        print(f"[DIAG] inventory_master_df rows: {inv_master_rows}")
    except Exception as exc:
        print(f"[DIAG] inventory_master_df 构建失败: {exc}")

    try:
        stock_df = _build_current_stock_df(stock_records)
        stock_df_rows = len(stock_df)
        print(f"[DIAG] stock_df rows (filtered by WARNING_WAREHOUSE_CODE={WARNING_WAREHOUSE_CODE}): {stock_df_rows}")
    except Exception as exc:
        print(f"[DIAG] stock_df 构建失败: {exc}")

    try:
        transit_df = _build_tplus_transit_from_stock_df(stock_records)
        transit_df_rows = len(transit_df)
        print(f"[DIAG] transit_df rows (from stock_records): {transit_df_rows}")
        if not transit_df.empty:
            print(f"[DIAG] transit_df sample:")
            print(transit_df.head(5).to_string(index=False))
    except Exception as exc:
        print(f"[DIAG] transit_df 构建失败: {exc}")

    results["dataframes"] = {
        "inventory_master_df_rows": inv_master_rows,
        "stock_df_rows": stock_df_rows,
        "transit_df_rows": transit_df_rows,
    }

    print("\n" + "=" * 60)
    print("[DIAG] 诊断完成")
    print("=" * 60)

    return results


def test_tplus_inventory_paging_candidates() -> list[dict[str, Any]]:
    """诊断函数：尝试多种 inventory/Query body 格式，找出能返回超过 100 条的方式。

    依次尝试 5 种 body 格式，每种打印：
    - body
    - response type
    - records count
    - 是否有 TotalCount / TotalPageNum
    - 前 1 条 Code

    Returns:
        每种尝试的结果列表
    """
    client = TPlusOpenAPIClient()
    all_results: list[dict[str, Any]] = []

    candidates = [
        # 1. 原始 body
        {
            "label": "原始 body",
            "body": {"param": {"SelectFields": "Code,Name,Specification,DefaultBarCode"}},
        },
        # 2. pageIndex/pageSize 在顶层
        {
            "label": "顶层 pageIndex/pageSize",
            "body": {"param": {"SelectFields": "Code,Name,Specification,DefaultBarCode"}, "pageIndex": 1, "pageSize": 500},
        },
        # 3. PageIndex/PageSize 在 param 内（大写）
        {
            "label": "param 内 PageIndex/PageSize 大写",
            "body": {"param": {"SelectFields": "Code,Name,Specification,DefaultBarCode", "PageIndex": 1, "PageSize": 500}},
        },
        # 4. pageIndex/pageSize 在 param 内（小写）
        {
            "label": "param 内 pageIndex/pageSize 小写",
            "body": {"param": {"SelectFields": "Code,Name,Specification,DefaultBarCode", "pageIndex": 1, "pageSize": 500}},
        },
        # 5. SaleDelivery 风格 body
        {
            "label": "SaleDelivery 风格",
            "body": {"selectFields": ["Code", "Name", "Specification", "DefaultBarCode"], "paramDic": {}, "pageIndex": 1, "pageSize": 500},
        },
    ]

    for candidate in candidates:
        label = candidate["label"]
        body = candidate["body"]

        print(f"\n{'=' * 60}")
        print(f"[DIAG-PAGING] 尝试: {label}")
        print(f"[DIAG-PAGING] body: {json.dumps(body, ensure_ascii=False)}")

        info: dict[str, Any] = {"label": label, "body": body}

        try:
            response = client._request("POST", INVENTORY_QUERY_ENDPOINT, json=body)

            info["response_type"] = type(response).__name__
            print(f"[DIAG-PAGING] response type: {info['response_type']}")

            records: list[dict[str, Any]] = []
            if isinstance(response, list):
                records = [item for item in response if isinstance(item, dict)]
            elif isinstance(response, dict):
                data = response.get("data")
                if isinstance(data, list):
                    records = [item for item in data if isinstance(item, dict)]
                elif isinstance(data, dict):
                    for key in ("TotalCount", "TotalPageNum", "pageIndex", "pageSize", "total", "totalCount"):
                        if key in data:
                            info[key] = data[key]
                            print(f"[DIAG-PAGING] data.{key} = {data[key]}")
                    for key in ("rows", "Rows", "items", "Items", "list", "List", "records", "Records"):
                        val = data.get(key)
                        if isinstance(val, list):
                            records = [item for item in val if isinstance(item, dict)]
                            break

            info["records_count"] = len(records)
            print(f"[DIAG-PAGING] records count: {len(records)}")

            if records:
                first = records[0]
                print(f"[DIAG-PAGING] first record Code={first.get('Code')}, Name={first.get('Name')}")

        except Exception as exc:
            info["error"] = str(exc)
            print(f"[DIAG-PAGING] ERROR: {exc}")

        all_results.append(info)

    print(f"\n{'=' * 60}")
    print(f"[DIAG-PAGING] 汇总:")
    for r in all_results:
        count = r.get("records_count", "ERROR")
        total = r.get("TotalCount", "N/A")
        print(f"  {r['label']}: records={count}, TotalCount={total}")
    print("=" * 60)

    return all_results


def test_tplus_warehouse_query_candidates() -> list[dict[str, Any]]:
    """诊断函数：探测仓库档案接口，找到"在途仓"的真实 WarehouseCode。

    候选接口：
    - /tplus/api/v2/warehouse/Query
    - /tplus/api/v2/Warehouse/Query
    - /tplus/api/v2/Store/Query
    - /tplus/api/v2/stock/warehouse/Query

    每个接口用 {"param": {}} 试探。

    Returns:
        每个接口的探测结果列表
    """
    client = TPlusOpenAPIClient()
    all_results: list[dict[str, Any]] = []

    candidates = [
        "/tplus/api/v2/warehouse/Query",
        "/tplus/api/v2/Warehouse/Query",
        "/tplus/api/v2/Store/Query",
        "/tplus/api/v2/stock/warehouse/Query",
    ]

    body = {"param": {}}

    for endpoint in candidates:
        print(f"\n{'=' * 60}")
        print(f"[DIAG-WH] 探测: {endpoint}")
        print(f"[DIAG-WH] body: {json.dumps(body, ensure_ascii=False)}")

        info: dict[str, Any] = {"endpoint": endpoint}

        try:
            response = client._request("POST", endpoint, json=body)

            info["response_type"] = type(response).__name__
            print(f"[DIAG-WH] response type: {info['response_type']}")

            records: list[dict[str, Any]] = []
            if isinstance(response, list):
                records = [item for item in response if isinstance(item, dict)]
            elif isinstance(response, dict):
                data = response.get("data")
                if isinstance(data, list):
                    records = [item for item in data if isinstance(item, dict)]
                elif isinstance(data, dict):
                    for key in ("rows", "Rows", "items", "Items", "list", "List", "records", "Records"):
                        val = data.get(key)
                        if isinstance(val, list):
                            records = [item for item in val if isinstance(item, dict)]
                            break

            info["records_count"] = len(records)
            print(f"[DIAG-WH] records count: {len(records)}")

            if records:
                print(f"[DIAG-WH] 前 20 条:")
                for i, rec in enumerate(records[:20]):
                    code = rec.get("Code") or rec.get("code") or rec.get("WarehouseCode") or rec.get("warehouseCode") or ""
                    name = rec.get("Name") or rec.get("name") or rec.get("WarehouseName") or rec.get("warehouseName") or ""
                    wh_code = rec.get("WarehouseCode") or rec.get("warehouseCode") or rec.get("WhCode") or ""
                    wh_name = rec.get("WarehouseName") or rec.get("warehouseName") or rec.get("WhName") or ""
                    print(f"  [{i}] Code={code}, Name={name}, WarehouseCode={wh_code}, WarehouseName={wh_name}")

                # 检查是否有"在途"相关记录
                transit_hits = []
                for rec in records[:20]:
                    name = str(rec.get("Name") or rec.get("name") or rec.get("WarehouseName") or rec.get("warehouseName") or "")
                    if "在途" in name:
                        transit_hits.append(rec)
                if transit_hits:
                    info["transit_hits"] = len(transit_hits)
                    print(f"[DIAG-WH] 命中'在途'的记录: {len(transit_hits)}")
                    for rec in transit_hits[:3]:
                        print(f"  -> {rec}")

        except Exception as exc:
            info["error"] = str(exc)
            print(f"[DIAG-WH] ERROR: {exc}")

        all_results.append(info)

    return all_results


def test_tplus_stock_with_warehouse_filter(
    warehouse_code: str = "",
    warehouse_name: str = "在途仓",
) -> list[dict[str, Any]]:
    """诊断函数：用仓库参数探测 currentStock/Query，找出在途仓编码。

    如果 warehouse_code 为空，会先从仓库档案探测。

    依次尝试 4 种 body 格式：
    1. {"param": {"WarehouseCode": "..."}}
    2. {"param": {"Warehouse": {"Code": "..."}}}
    3. {"param": {"WarehouseCodes": ["..."]}}
    4. {"param": {"WarehouseName": "..."}}

    Args:
        warehouse_code: 在途仓编码（为空时跳过编码类探测）
        warehouse_name: 在途仓名称（默认"在途仓"）

    Returns:
        每种尝试的结果列表
    """
    client = TPlusOpenAPIClient()
    all_results: list[dict[str, Any]] = []

    candidates: list[dict[str, Any]] = []

    if warehouse_code:
        candidates.extend([
            {
                "label": f"WarehouseCode={warehouse_code}",
                "body": {"param": {"WarehouseCode": warehouse_code}},
            },
            {
                "label": f"Warehouse.Code={warehouse_code}",
                "body": {"param": {"Warehouse": {"Code": warehouse_code}}},
            },
            {
                "label": f"WarehouseCodes=[{warehouse_code}]",
                "body": {"param": {"WarehouseCodes": [warehouse_code]}},
            },
        ])

    if warehouse_name:
        candidates.append({
            "label": f"WarehouseName={warehouse_name}",
            "body": {"param": {"WarehouseName": warehouse_name}},
        })

    if not candidates:
        print("[DIAG-STOCK] 无探测候选（warehouse_code 和 warehouse_name 都为空）")
        return []

    for candidate in candidates:
        label = candidate["label"]
        body = candidate["body"]

        print(f"\n{'=' * 60}")
        print(f"[DIAG-STOCK] 尝试: {label}")
        print(f"[DIAG-STOCK] body: {json.dumps(body, ensure_ascii=False)}")

        info: dict[str, Any] = {"label": label, "body": body}

        try:
            response = client._request("POST", CURRENT_STOCK_QUERY_ENDPOINT, json=body)

            info["response_type"] = type(response).__name__
            print(f"[DIAG-STOCK] response type: {info['response_type']}")

            records: list[dict[str, Any]] = []
            if isinstance(response, list):
                records = [item for item in response if isinstance(item, dict)]
            elif isinstance(response, dict):
                data = response.get("data")
                if isinstance(data, list):
                    records = [item for item in data if isinstance(item, dict)]
                elif isinstance(data, dict):
                    for key in ("rows", "Rows", "items", "Items", "list", "List", "records", "Records"):
                        val = data.get(key)
                        if isinstance(val, list):
                            records = [item for item in val if isinstance(item, dict)]
                            break

            info["records_count"] = len(records)
            print(f"[DIAG-STOCK] records count: {len(records)}")

            if records:
                print(f"[DIAG-STOCK] 前 3 条:")
                for i, rec in enumerate(records[:3]):
                    print(f"  [{i}] WarehouseCode={rec.get('WarehouseCode')}, "
                          f"WarehouseName={rec.get('WarehouseName')}, "
                          f"InventoryCode={rec.get('InventoryCode')}, "
                          f"ExistingQuantity={rec.get('ExistingQuantity')}")

        except Exception as exc:
            info["error"] = str(exc)
            print(f"[DIAG-STOCK] ERROR: {exc}")

        all_results.append(info)

    print(f"\n{'=' * 60}")
    print(f"[DIAG-STOCK] 汇总:")
    for r in all_results:
        count = r.get("records_count", "ERROR")
        err = r.get("error", "")
        print(f"  {r['label']}: records={count}" + (f", error={err}" if err else ""))
    print("=" * 60)

    return all_results


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
    """从存货档案 API 响应构建 DataFrame。

    只输出 存货编码、存货、尺码，不输出销量字段。
    尺码优先取 DynamicPropertyValues[0]（与销货单口径一致），fallback 取 Specification。
    """
    rows = []
    for item in records:
        rows.append(
            {
                "存货编码": clean_code(_field(item, "Code", "code", "InventoryCode", "inventoryCode", "InvCode")),
                "存货": str(_field(item, "Name", "name", "InventoryName", "inventoryName", "InvName") or ""),
                "尺码": clean_size(
                    _first_dynamic_value(item)
                    or _field(item, "Specification", "specification", "Size", "size", "FreeItem0")
                ),
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("查询存货档案接口未返回有效数据")

    df["存货编码"] = df["存货编码"].apply(clean_code)
    df["尺码"] = df["尺码"].apply(clean_size)

    return df.drop_duplicates(subset=["存货编码", "尺码"])


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
                "尺码": clean_size(
                    _first_dynamic_value(item)
                    or _field(item, "Specification", "specification", "Size", "size", "FreeItem0")
                ),
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
        df["仓库编码"] = df["仓库编码"].apply(_normalize_warehouse_code)
        df = df[df["仓库编码"] == WARNING_WAREHOUSE_CODE].copy()
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


def _build_tplus_transit_from_stock_df(stock_records: list[dict[str, Any]]) -> pd.DataFrame:
    """从 currentStock/Query 返回的 stock_records 中提取在途仓数量。

    在途仓 = T+ currentStock 中在途仓仓库的 ExistingQuantity（fallback Quantity）。
    在途（未发货） = 0（来自人工导入的 transit_df）。

    筛选规则：仓库名称命中 TPLUS_TRANSIT_WAREHOUSE_NAMES，
    或仓库编码命中 TPLUS_TRANSIT_WAREHOUSE_CODES 的记录。

    Args:
        stock_records: currentStock/Query 原始返回的记录列表

    Returns:
        DataFrame 列: 存货编码, 尺码, 在途仓（数量）, 在途（未发货）（固定为0）
    """
    if not stock_records:
        return pd.DataFrame(columns=["存货编码", "尺码", "在途仓", "在途（未发货）"])

    rows = []
    for item in stock_records:
        warehouse_code = str(
            _field(item, "WarehouseCode", "warehouseCode", "WhCode", "whCode") or ""
        ).strip()
        warehouse_name = str(
            _field(item, "WarehouseName", "warehouseName", "WhName", "whName") or ""
        ).strip()

        # 判断是否为在途仓
        is_transit = False
        if TPLUS_TRANSIT_WAREHOUSE_NAMES:
            for name in TPLUS_TRANSIT_WAREHOUSE_NAMES:
                if name and name in warehouse_name:
                    is_transit = True
                    break
        if not is_transit and TPLUS_TRANSIT_WAREHOUSE_CODES:
            normalized_code = _normalize_warehouse_code(warehouse_code)
            for code in TPLUS_TRANSIT_WAREHOUSE_CODES:
                if code and _normalize_warehouse_code(code) == normalized_code:
                    is_transit = True
                    break

        if not is_transit:
            continue

        code = clean_code(
            _field(item, "InventoryCode", "inventoryCode", "Code", "code", "InvCode")
        )
        size = clean_size(
            _first_dynamic_value(item)
            or _field(item, "Specification", "specification", "Size", "size", "FreeItem0")
        )
        quantity = _to_number(
            _field(item, "ExistingQuantity", "existingQuantity", "Quantity", "quantity")
        )

        if code:
            rows.append({
                "存货编码": code,
                "尺码": size,
                "在途仓": quantity,
                "在途（未发货）": 0,
            })

    if not rows:
        return pd.DataFrame(columns=["存货编码", "尺码", "在途仓", "在途（未发货）"])

    df = pd.DataFrame(rows)
    df["在途仓"] = pd.to_numeric(df["在途仓"], errors="coerce").fillna(0)

    # 按 存货编码+尺码 聚合：在途仓求和，在途（未发货）保持 0
    agg_df = (
        df.groupby(["存货编码", "尺码"], as_index=False)
        .agg({
            "在途仓": "sum",
            "在途（未发货）": "first",
        })
    )
    return agg_df


def _build_tplus_size_alias_map(stock_records: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
    """从当前库存记录中构建尺码别名映射。

    同一条库存记录里如果 Specification 和 DynamicPropertyValues[0] 都存在且不同，
    说明 存货档案 的 Specification 尺码 应映射为 销货单 的 DynamicPropertyValues 尺码。

    返回: {(存货编码, 档案尺码): 真实业务尺码}
    """
    alias: dict[tuple[str, str], str] = {}
    for item in stock_records:
        code = clean_code(_field(item, "InventoryCode", "inventoryCode", "Code", "code", "InvCode"))
        spec_size = clean_size(_field(item, "Specification", "specification", "Size", "size", "FreeItem0"))
        dynamic_size = clean_size(_first_dynamic_value(item))
        if spec_size and dynamic_size and spec_size != dynamic_size:
            alias[(code, spec_size)] = dynamic_size
    return alias


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


def _build_recent_sales_summary_df(
    rows: list[dict[str, Any]],
    days: int = SAFE_DAYS,
    column_name: str = "近7天销量",
) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["存货编码", "尺码", column_name, "日均销量"])

    sales_df = pd.DataFrame(rows)
    sales_df["销售数量"] = pd.to_numeric(sales_df["销售数量"], errors="coerce").fillna(0)

    if WARNING_WAREHOUSE_CODE and "仓库编码" in sales_df.columns:
        warehouse_codes = sales_df["仓库编码"].fillna("").astype(str).str.strip()
        if warehouse_codes.ne("").any():
            sales_df = sales_df[warehouse_codes == WARNING_WAREHOUSE_CODE].copy()

    if sales_df.empty:
        return pd.DataFrame(columns=["存货编码", "尺码", column_name, "日均销量"])

    result = (
        sales_df.groupby(["存货编码", "尺码"], as_index=False)["销售数量"]
        .sum()
        .rename(columns={"销售数量": column_name})
    )
    result[column_name] = result[column_name].clip(lower=0)
    result["日均销量"] = result[column_name] / days
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

    # 从 cache_key 中获取实际的列名，兼容近7天/近90天等不同查询
    column_name = cache_key.get("column_name", "近7天销量")
    return pd.DataFrame(rows, columns=["存货编码", "尺码", column_name, "日均销量"])


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
