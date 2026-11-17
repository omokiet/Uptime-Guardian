import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Tuple
import uuid
from sqlalchemy import update
from services.common.config import settings
from services.common.database import AsyncSessionLocal
from services.common.models import CheckResult
from services.common.rabbitmq import publish_message
from services.common.redis_client import get_redis_client

logger = logging.getLogger(__name__)


def evaluate_quorum_votes(
    votes_dict: Dict[str, dict],
    quorum_threshold: int,
    quorum_regions: List[str],
    is_timeout: bool = False,
) -> Tuple[str, Optional[str]]:
    total_regions = len(quorum_regions)
    fail_regions = []
    pass_count = 0

    for reg in quorum_regions:
        reg_vote = votes_dict.get(reg)
        if not reg_vote:
            continue
        if isinstance(reg_vote, str):
            try:
                reg_vote = json.loads(reg_vote)
            except Exception:
                continue
        if not isinstance(reg_vote, dict):
            continue

        status = reg_vote.get("status")
        if status == "FAIL":
            fail_regions.append(reg)
        elif status == "PASS":
            pass_count += 1

    fail_count = len(fail_regions)

    if fail_count >= quorum_threshold:
        reason = f"Quorum confirmed outage ({fail_count}/{total_regions} regions failed: {', '.join(fail_regions)})"
        return "OUTAGE_CONFIRMED", reason

    max_possible_fails = total_regions - pass_count
    if max_possible_fails < quorum_threshold:
        reason = (
            f"Quorum suppressed alert ({pass_count}/{total_regions} regions passed, "
            f"threshold {quorum_threshold} unreachable)"
        )
        return "SUPPRESSED", reason

    if is_timeout:
        reason = (
            f"Quorum challenge timed out with {fail_count} failures, "
            f"below threshold {quorum_threshold}. Alert suppressed."
        )
        return "SUPPRESSED", reason

    return "PENDING", None


async def record_vote_and_evaluate(
    challenge_id: str,
    monitor_id: str,
    initiator_job_id: str,
    region_id: str,
    vote_data: dict,
    quorum_threshold: int,
    quorum_regions: List[str],
    url: str,
    redis_client: Optional[Any] = None,
) -> str:
    r_client = redis_client or get_redis_client()
    session_key = f"quorum:session:{challenge_id}"
    lock_key = f"quorum:active:{monitor_id}"

    pipe = r_client.pipeline()
    pipe.hset(session_key, region_id, json.dumps(vote_data))
    pipe.expire(session_key, settings.QUORUM_SESSION_TTL_SECONDS)
    await pipe.execute()

    raw_session = await r_client.hgetall(session_key) or {}
    if not isinstance(raw_session, dict):
        raw_session = {}
    existing_decision = raw_session.get("decision")
    if existing_decision:
        return str(existing_decision)

    parsed_votes: Dict[str, dict] = {}
    for k, v in raw_session.items():
        if k == "decision" or str(k).startswith("_"):
            continue
        try:
            parsed_votes[str(k)] = json.loads(v) if isinstance(v, (str, bytes)) else v
        except Exception:
            continue

    decision, reason = evaluate_quorum_votes(
        votes_dict=parsed_votes,
        quorum_threshold=quorum_threshold,
        quorum_regions=quorum_regions,
        is_timeout=False,
    )

    if decision == "OUTAGE_CONFIRMED":
        acquired = await r_client.hsetnx(session_key, "decision", "OUTAGE_CONFIRMED")
        if acquired:
            alert_payload = {
                "job_id": challenge_id,
                "monitor_id": monitor_id,
                "url": url,
                "is_success": False,
                "status_code": vote_data.get("status_code"),
                "response_time_ms": vote_data.get("response_time_ms"),
                "error_message": reason or "Quorum confirmed outage",
                "quorum_confirmed": True,
            }
            await publish_message(settings.RABBITMQ_QUEUE_ALERT_EVENTS, alert_payload)
        return "OUTAGE_CONFIRMED"

    if decision == "SUPPRESSED":
        acquired = await r_client.hsetnx(session_key, "decision", "SUPPRESSED")
        if acquired:
            target_job_id = initiator_job_id or raw_session.get("_initiator_job_id")
            if target_job_id:
                try:
                    if isinstance(target_job_id, bytes):
                        target_job_id = target_job_id.decode("utf-8")
                    job_uuid = uuid.UUID(target_job_id)
                    async with AsyncSessionLocal() as session:
                        stmt = (
                            update(CheckResult)
                            .where(CheckResult.job_id == job_uuid)
                            .values(is_suppressed=True)
                        )
                        await session.execute(stmt)
                        await session.commit()
                except Exception as exc:
                    logger.error("Failed to update suppressed CheckResult %s: %s", target_job_id, exc)
            await r_client.delete(lock_key)
        return "SUPPRESSED"

    return "PENDING"


async def resolve_quorum_on_timeout(
    challenge_id: str,
    monitor_id: str,
    initiator_job_id: str,
    quorum_threshold: int,
    quorum_regions: List[str],
    url: str,
    timeout_seconds: Optional[float] = None,
    redis_client: Optional[Any] = None,
) -> str:
    wait_sec = timeout_seconds if timeout_seconds is not None else settings.QUORUM_CHALLENGE_TIMEOUT_SECONDS
    await asyncio.sleep(wait_sec)

    r_client = redis_client or get_redis_client()
    session_key = f"quorum:session:{challenge_id}"
    lock_key = f"quorum:active:{monitor_id}"

    raw_session = await r_client.hgetall(session_key) or {}
    if not isinstance(raw_session, dict):
        raw_session = {}
    existing_decision = raw_session.get("decision")
    if existing_decision:
        return str(existing_decision)

    parsed_votes: Dict[str, dict] = {}
    for k, v in raw_session.items():
        if k == "decision" or str(k).startswith("_"):
            continue
        try:
            parsed_votes[str(k)] = json.loads(v) if isinstance(v, (str, bytes)) else v
        except Exception:
            continue

    decision, reason = evaluate_quorum_votes(
        votes_dict=parsed_votes,
        quorum_threshold=quorum_threshold,
        quorum_regions=quorum_regions,
        is_timeout=True,
    )

    if decision == "OUTAGE_CONFIRMED":
        acquired = await r_client.hsetnx(session_key, "decision", "OUTAGE_CONFIRMED")
        if acquired:
            alert_payload = {
                "job_id": challenge_id,
                "monitor_id": monitor_id,
                "url": url,
                "is_success": False,
                "error_message": reason or "Quorum confirmed outage",
                "quorum_confirmed": True,
            }
            await publish_message(settings.RABBITMQ_QUEUE_ALERT_EVENTS, alert_payload)
        return "OUTAGE_CONFIRMED"

    acquired = await r_client.hsetnx(session_key, "decision", "SUPPRESSED")
    if acquired:
        target_job_id = initiator_job_id or raw_session.get("_initiator_job_id")
        if target_job_id:
            try:
                if isinstance(target_job_id, bytes):
                    target_job_id = target_job_id.decode("utf-8")
                job_uuid = uuid.UUID(target_job_id)
                async with AsyncSessionLocal() as session:
                    stmt = (
                        update(CheckResult)
                        .where(CheckResult.job_id == job_uuid)
                        .values(is_suppressed=True)
                    )
                    await session.execute(stmt)
                    await session.commit()
            except Exception as exc:
                logger.error("Failed to update suppressed CheckResult %s on timeout: %s", target_job_id, exc)
        await r_client.delete(lock_key)

    return "SUPPRESSED"
