import datetime
import re
from typing import List, Optional, Tuple
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def get_iso_week_bounds(dt: datetime.datetime) -> Tuple[datetime.datetime, datetime.datetime, str]:
    utc_dt = dt.astimezone(datetime.timezone.utc)
    year, week, weekday = utc_dt.isocalendar()
    monday = utc_dt.date() - datetime.timedelta(days=weekday - 1)
    start_dt = datetime.datetime.combine(monday, datetime.time.min, tzinfo=datetime.timezone.utc)
    end_dt = start_dt + datetime.timedelta(days=7)
    partition_name = f"check_results_y{year}_w{week:02d}"
    return start_dt, end_dt, partition_name


def _get_dialect_name(session: AsyncSession) -> str:
    bind = getattr(session, "bind", None)
    if bind is None and hasattr(session, "get_bind"):
        try:
            bind = session.get_bind()
        except Exception:
            bind = None
    return getattr(getattr(bind, "dialect", None), "name", "")


async def ensure_future_partitions(
    session: AsyncSession,
    weeks_ahead: int = 4,
    current_time: Optional[datetime.datetime] = None,
) -> List[str]:
    if _get_dialect_name(session) != "postgresql":
        return []

    base_time = current_time or datetime.datetime.now(datetime.timezone.utc)
    ensured: List[str] = []

    await session.execute(
        text("CREATE TABLE IF NOT EXISTS check_results_default PARTITION OF check_results DEFAULT;")
    )
    ensured.append("check_results_default")

    for i in range(weeks_ahead + 1):
        target = base_time + datetime.timedelta(weeks=i)
        start_dt, end_dt, part_name = get_iso_week_bounds(target)
        if part_name not in ensured:
            start_iso = start_dt.isoformat()
            end_iso = end_dt.isoformat()
            ddl = (
                f"CREATE TABLE IF NOT EXISTS {part_name} PARTITION OF check_results "
                f"FOR VALUES FROM ('{start_iso}') TO ('{end_iso}');"
            )
            await session.execute(text(ddl))
            ensured.append(part_name)

    await session.commit()
    return ensured


async def drop_expired_partitions(
    session: AsyncSession,
    retention_days: int = 7,
    current_time: Optional[datetime.datetime] = None,
) -> List[str]:
    if _get_dialect_name(session) != "postgresql":
        return []

    base_time = current_time or datetime.datetime.now(datetime.timezone.utc)
    cutoff = base_time - datetime.timedelta(days=retention_days)

    query = text(
        "SELECT inhrelid::regclass::text AS part_name "
        "FROM pg_inherits "
        "WHERE inhparent = 'check_results'::regclass;"
    )
    result = await session.execute(query)
    partition_names = result.scalars().all()

    pattern = re.compile(r"^check_results_y(\d{4})_w(\d{2})$")
    dropped: List[str] = []

    for name in partition_names:
        clean_name = name.split(".")[-1].strip('"')
        match = pattern.match(clean_name)
        if not match:
            continue

        year = int(match.group(1))
        week = int(match.group(2))
        try:
            sample_dt = datetime.datetime.fromisocalendar(year, week, 1).replace(
                tzinfo=datetime.timezone.utc
            )
            _, end_dt, _ = get_iso_week_bounds(sample_dt)
        except ValueError:
            continue

        if end_dt <= cutoff:
            await session.execute(text(f"DROP TABLE IF EXISTS {clean_name};"))
            dropped.append(clean_name)

    if dropped:
        await session.commit()
    return dropped
