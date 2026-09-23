from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from services.common.models import CheckResult, HourlyUptimeSummary


async def aggregate_hourly_uptime(
    session: AsyncSession,
    target_hour: Optional[datetime] = None,
) -> int:
    if target_hour is None:
        now_utc = datetime.now(timezone.utc)
        target_hour = now_utc.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    else:
        target_hour = target_hour.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)

    start_window = target_hour
    end_window = target_hour + timedelta(hours=1)

    stmt = (
        select(
            CheckResult.monitor_id,
            func.count(CheckResult.id).label("total_checks"),
            func.sum(case((CheckResult.is_success == True, 1), else_=0)).label("success_checks"),
            func.coalesce(func.avg(CheckResult.response_time_ms), 0).label("avg_rtt"),
        )
        .where(
            CheckResult.created_at >= start_window,
            CheckResult.created_at < end_window,
        )
        .group_by(CheckResult.monitor_id)
    )

    result = await session.execute(stmt)
    rows = result.all()

    if not rows:
        return 0

    processed_count = 0
    for row in rows:
        monitor_id = row.monitor_id
        total_checks = int(row.total_checks or 0)
        success_checks = int(row.success_checks or 0)
        avg_rtt = int(round(float(row.avg_rtt or 0)))

        if total_checks > 0:
            uptime_pct = (Decimal(success_checks) / Decimal(total_checks) * Decimal("100")).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
        else:
            uptime_pct = Decimal("0.00")

        existing_stmt = select(HourlyUptimeSummary).where(
            HourlyUptimeSummary.monitor_id == monitor_id,
            HourlyUptimeSummary.hour_timestamp == target_hour,
        )
        existing_result = await session.execute(existing_stmt)
        summary = existing_result.scalar_one_or_none()

        if summary:
            summary.total_checks = total_checks
            summary.success_checks = success_checks
            summary.avg_response_time_ms = avg_rtt
            summary.uptime_percentage = uptime_pct
        else:
            summary = HourlyUptimeSummary(
                monitor_id=monitor_id,
                hour_timestamp=target_hour,
                total_checks=total_checks,
                success_checks=success_checks,
                avg_response_time_ms=avg_rtt,
                uptime_percentage=uptime_pct,
            )
            session.add(summary)

        processed_count += 1

    await session.commit()
    return processed_count


async def purge_old_check_results(
    session: AsyncSession,
    retention_days: int = 7,
    current_time: Optional[datetime] = None,
    batch_size: int = 5000,
) -> int:
    base_time = current_time or datetime.now(timezone.utc)
    cutoff = base_time - timedelta(days=retention_days)

    total_deleted = 0
    while True:
        subquery = (
            select(CheckResult.id)
            .where(CheckResult.created_at < cutoff)
            .limit(batch_size)
            .scalar_subquery()
        )

        delete_stmt = delete(CheckResult).where(CheckResult.id.in_(subquery))
        result = await session.execute(delete_stmt)
        deleted_count = result.rowcount

        await session.commit()
        total_deleted += deleted_count

        if deleted_count < batch_size:
            break

    return total_deleted
