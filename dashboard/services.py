import sqlite3
import hashlib
import json
import logging
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, time as datetime_time, timedelta, timezone as datetime_timezone
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.dateparse import parse_date


logger = logging.getLogger(__name__)

QUOTA_DISABLED_REASON = "Đã dùng hết hạn mức"
LEGACY_DELETED_KEY_REASON = "Key cũ đã bị xóa; cần tạo API mới"


def _database_connection():
    database_uri = f"file:{settings.NINEROUTER_SQLITE_FILE}?mode=ro"
    try:
        connection = sqlite3.connect(database_uri, uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection
    except sqlite3.Error as error:
        raise RuntimeError(f"Không thể đọc cơ sở dữ liệu ALT: {error}") from error


def available_api_keys():
    try:
        with _database_connection() as connection:
            rows = connection.execute(
                "SELECT id, COALESCE(name, 'API chưa đặt tên') AS name "
                "FROM apiKeys WHERE isActive = 1 ORDER BY name"
            ).fetchall()
    except sqlite3.Error as error:
        raise RuntimeError(f"Không thể đọc danh sách API ALT: {error}") from error
    return [{"id": str(row["id"]), "name": row["name"]} for row in rows]


class RouterApiError(RuntimeError):
    pass


class RouterApiNotFoundError(RouterApiError):
    pass


def _router_cli_token():
    data_dir = settings.NINEROUTER_SQLITE_FILE.parent.parent
    machine_id = (data_dir / "machine-id").read_text().strip()
    cli_secret = (data_dir / "auth" / "cli-secret").read_text().strip()
    return hashlib.sha256(f"{machine_id}9r-cli-auth{cli_secret}".encode()).hexdigest()[:16]


def _router_request(method, path, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        f"http://127.0.0.1:20128{path}", data=body, method=method,
        headers={"Content-Type": "application/json", "x-9r-cli-token": _router_cli_token()},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise RouterApiNotFoundError("API không còn tồn tại trên hệ thống ALT.") from exc
        raise RouterApiError("Không thể cập nhật API trên hệ thống ALT.") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RouterApiError("Không thể cập nhật API trên hệ thống ALT.") from exc


def create_router_api_key(name):
    return _router_request("POST", "/api/keys", {"name": name})


def delete_router_api_key(external_id):
    return _router_request("DELETE", f"/api/keys/{external_id}")


def set_router_api_key_active(external_id, is_active):
    return _router_request("PUT", f"/api/keys/{external_id}", {"isActive": is_active})


def all_time_cost(api_key_ids):
    return sum(usage_totals_by_api_id(api_key_ids).values(), Decimal("0"))


def customer_spent(user):
    from .models import ManagedApiKey, UserApiAccess

    api_ids = list(UserApiAccess.objects.filter(user=user).values_list("external_api_key_id", flat=True))
    closed = ManagedApiKey.objects.filter(user=user, is_active=False).aggregate(total=models.Sum("closed_cost"))["total"] or Decimal("0")
    return all_time_cost(api_ids) + closed


def reactivate_quota_disabled_keys(user_id):
    from .models import CustomerAccount, ManagedApiKey, UserApiAccess

    result = {"reactivated": 0, "missing": 0, "failed": 0}
    account = (
        CustomerAccount.objects.select_related("user")
        .filter(user_id=user_id)
        .first()
    )
    if not account or not account.user.is_active:
        return result
    if customer_spent(account.user) >= account.credit_limit:
        return result

    keys = ManagedApiKey.objects.filter(
        user_id=user_id,
        is_active=False,
        disabled_reason=QUOTA_DISABLED_REASON,
    )
    for key in keys:
        try:
            set_router_api_key_active(key.external_api_key_id, True)
        except RouterApiNotFoundError:
            key.disabled_reason = LEGACY_DELETED_KEY_REASON
            key.save(update_fields=["disabled_reason"])
            UserApiAccess.objects.filter(
                user_id=user_id,
                external_api_key_id=key.external_api_key_id,
            ).delete()
            result["missing"] += 1
            logger.warning(
                "Không thể mở lại key legacy đã bị xóa managed_key_id=%s user_id=%s",
                key.id,
                user_id,
            )
        except RouterApiError:
            result["failed"] += 1
            logger.exception(
                "Không thể mở lại API theo hạn mức managed_key_id=%s user_id=%s",
                key.id,
                user_id,
            )
        else:
            key.is_active = True
            key.disabled_reason = ""
            key.disabled_at = None
            key.closed_cost = Decimal("0")
            key.save(
                update_fields=[
                    "is_active",
                    "disabled_reason",
                    "disabled_at",
                    "closed_cost",
                ]
            )
            UserApiAccess.objects.get_or_create(
                user_id=user_id,
                external_api_key_id=key.external_api_key_id,
                defaults={"api_name": key.api_name},
            )
            result["reactivated"] += 1
    return result


def member_cost_report(query, api_key_ids):
    period, start_date, end_date, start_at, end_at, label = _range_from_query(query)
    api_key_ids = list(dict.fromkeys(str(api_id) for api_id in api_key_ids))
    if not api_key_ids:
        return {
            "period": period,
            "start_date": start_date,
            "end_date": end_date,
            "range_label": label,
            "totals": {},
        }

    placeholders = ", ".join("?" for _ in api_key_ids)
    query = f"""
        SELECT keys.id AS api_id, usage.timestamp, usage.cost
        FROM apiKeys AS keys
        JOIN usageHistory AS usage ON usage.apiKey = keys.key
        WHERE keys.id IN ({placeholders})
    """
    try:
        with _database_connection() as connection:
            rows = connection.execute(query, api_key_ids).fetchall()
    except sqlite3.Error as error:
        raise RuntimeError(f"Không thể tổng hợp chi phí người dùng: {error}") from error

    totals = defaultdict(lambda: Decimal("0"))
    for row in rows:
        occurred_at = _local_datetime(row["timestamp"])
        if occurred_at is None:
            continue
        if start_at is not None and not start_at <= occurred_at <= end_at:
            continue
        try:
            totals[str(row["api_id"])] += Decimal(str(row["cost"] or 0))
        except InvalidOperation:
            pass
    return {
        "period": period,
        "start_date": start_date,
        "end_date": end_date,
        "range_label": label,
        "totals": dict(totals),
    }


def usage_totals_by_api_id(api_key_ids):
    return member_cost_report({"period": "all"}, api_key_ids)["totals"]


def _usage_rows(allowed_api_key_ids=None):
    query = """
        SELECT
            usage.id,
            usage.timestamp,
            usage.provider,
            usage.model,
            usage.endpoint,
            usage.promptTokens,
            usage.completionTokens,
            usage.cost,
            usage.status,
            COALESCE(keys.name, 'API không xác định') AS api_name
        FROM usageHistory AS usage
        LEFT JOIN apiKeys AS keys ON keys.key = usage.apiKey
    """
    parameters = []
    if allowed_api_key_ids is not None:
        allowed_api_key_ids = list(allowed_api_key_ids)
        if not allowed_api_key_ids:
            return []
        placeholders = ", ".join("?" for _ in allowed_api_key_ids)
        query += f" WHERE keys.id IN ({placeholders})"
        parameters.extend(allowed_api_key_ids)
    query += " ORDER BY usage.timestamp"

    try:
        with _database_connection() as connection:
            return connection.execute(query, parameters).fetchall()
    except sqlite3.Error as error:
        raise RuntimeError(f"Không thể đọc lịch sử ALT: {error}") from error


def _local_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, datetime_timezone.utc)
    return timezone.localtime(parsed)


def _range_from_query(query):
    today = timezone.localdate()
    period = query.get("period", "all")

    if period == "all":
        start_date = None
        end_date = None
        label = "Toàn bộ lịch sử"
    elif period == "today":
        start_date = end_date = today
        label = "Hôm nay"
    elif period == "custom":
        start_date = parse_date(query.get("start", "")) or today
        end_date = parse_date(query.get("end", "")) or start_date
        if start_date > end_date:
            start_date, end_date = end_date, start_date
        label = f"{start_date.strftime('%d/%m/%Y')} – {end_date.strftime('%d/%m/%Y')}"
    else:
        period = "month"
        start_date = today.replace(day=1)
        next_month = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1)
        end_date = next_month - timedelta(days=1)
        label = "Tháng này"

    if start_date is None:
        start_at = end_at = None
    else:
        current_tz = timezone.get_current_timezone()
        start_at = timezone.make_aware(
            datetime.combine(start_date, datetime_time.min), current_tz
        )
        end_at = timezone.make_aware(
            datetime.combine(end_date, datetime_time.max), current_tz
        )
    return period, start_date, end_date, start_at, end_at, label


def usage_report(query, allowed_api_key_ids=None):
    period, start_date, end_date, start_at, end_at, label = _range_from_query(query)
    grouped = defaultdict(lambda: {"requests": 0, "cost": Decimal("0")})
    latest_record_at = None

    for record in _usage_rows(allowed_api_key_ids):
        occurred_at = _local_datetime(record["timestamp"])
        if occurred_at is None:
            continue
        if latest_record_at is None or occurred_at > latest_record_at:
            latest_record_at = occurred_at
        if start_at is not None and not start_at <= occurred_at <= end_at:
            continue

        api_name = record["api_name"]
        grouped[api_name]["requests"] += 1
        try:
            grouped[api_name]["cost"] += Decimal(str(record["cost"] or 0))
        except InvalidOperation:
            pass

    rows = [
        {"api_name": name, "requests": values["requests"], "cost": values["cost"]}
        for name, values in grouped.items()
    ]
    rows.sort(key=lambda row: (-row["cost"], row["api_name"].lower()))
    total_requests = sum(row["requests"] for row in rows)
    total_cost = sum((row["cost"] for row in rows), Decimal("0"))
    for row in rows:
        row["share"] = (
            (row["cost"] / total_cost * 100).quantize(Decimal("0.1"))
            if total_cost
            else Decimal("0")
        )

    return {
        "period": period,
        "start_date": start_date,
        "end_date": end_date,
        "range_label": label,
        "rows": rows,
        "total_requests": total_requests,
        "total_cost": total_cost,
        "api_count": len(rows),
        "average_cost": total_cost / total_requests if total_requests else Decimal("0"),
        "latest_record_at": latest_record_at,
    }


def usage_activity_report(query, allowed_api_key_ids=None, page=1, page_size=50):
    period, start_date, end_date, start_at, end_at, label = _range_from_query(query)
    records = []
    successful_requests = 0
    failed_requests = 0
    total_prompt_tokens = 0
    total_completion_tokens = 0

    for record in _usage_rows(allowed_api_key_ids):
        occurred_at = _local_datetime(record["timestamp"])
        if occurred_at is None:
            continue
        if start_at is not None and not start_at <= occurred_at <= end_at:
            continue

        status = str(record["status"] or "unknown").lower()
        is_success = status in {"ok", "success", "completed", "200"}
        if is_success:
            successful_requests += 1
        else:
            failed_requests += 1

        prompt_tokens = int(record["promptTokens"] or 0)
        completion_tokens = int(record["completionTokens"] or 0)
        total_prompt_tokens += prompt_tokens
        total_completion_tokens += completion_tokens
        try:
            cost = Decimal(str(record["cost"] or 0))
        except InvalidOperation:
            cost = Decimal("0")

        records.append({
            "request_id": record["id"],
            "occurred_at": occurred_at,
            "api_name": record["api_name"],
            "provider": record["provider"] or "—",
            "model": record["model"] or "—",
            "endpoint": record["endpoint"] or "—",
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "cost": cost,
            "status": status,
            "is_success": is_success,
        })

    records.sort(key=lambda record: (record["occurred_at"], record["request_id"]), reverse=True)
    total_records = len(records)
    total_pages = max((total_records + page_size - 1) // page_size, 1)
    try:
        current_page = int(page)
    except (TypeError, ValueError):
        current_page = 1
    current_page = min(max(current_page, 1), total_pages)
    offset = (current_page - 1) * page_size

    return {
        "activity_rows": records[offset:offset + page_size],
        "activity_total": total_records,
        "activity_successful": successful_requests,
        "activity_failed": failed_requests,
        "activity_prompt_tokens": total_prompt_tokens,
        "activity_completion_tokens": total_completion_tokens,
        "activity_page": current_page,
        "activity_total_pages": total_pages,
        "activity_has_previous": current_page > 1,
        "activity_has_next": current_page < total_pages,
        "activity_previous_page": current_page - 1,
        "activity_next_page": current_page + 1,
        "activity_period": period,
        "activity_start_date": start_date,
        "activity_end_date": end_date,
        "activity_range_label": label,
    }
