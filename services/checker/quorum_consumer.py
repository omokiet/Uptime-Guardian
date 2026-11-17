from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict
from pydantic import ValidationError
from services.alerter.quorum_engine import record_vote_and_evaluate
from services.checker.checker import execute_check
from services.common.config import settings
from services.common.metrics import CHECKER_PROCESSING_ERRORS_TOTAL
from services.common.rabbitmq import get_rabbitmq_connection, setup_quorum_topology
from services.common.redis_client import get_redis_client
from services.common.schemas import QuorumChallengeMessage

logger = logging.getLogger(__name__)


async def process_quorum_challenge(
    payload: Dict[str, Any],
    redis_client: Any,
) -> bool:
    try:
        challenge = QuorumChallengeMessage.model_validate(payload)
    except ValidationError as exc:
        CHECKER_PROCESSING_ERRORS_TOTAL.inc()
        logger.error("Invalid quorum challenge payload schema: %s", exc)
        return False

    if challenge.initiator_region == settings.REGION_ID:
        return True

    if settings.REGION_ID not in challenge.quorum_regions:
        return True

    probe_timeout = min(float(challenge.timeout_seconds), 5.0)
    is_success, status_code, latency_ms, error_msg, _ = await execute_check(
        job_id=challenge.challenge_id,
        monitor_id=challenge.monitor_id,
        url=challenge.url,
        method=challenge.method,
        timeout_seconds=int(probe_timeout),
        expected_status_code=challenge.expected_status_code,
        redis_client=redis_client,
    )

    vote = {
        "status": "PASS" if is_success else "FAIL",
        "status_code": status_code,
        "response_time_ms": latency_ms,
        "error_message": error_msg,
        "voted_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    await record_vote_and_evaluate(
        challenge_id=challenge.challenge_id,
        monitor_id=challenge.monitor_id,
        initiator_job_id=challenge.initiator_job_id or "",
        region_id=settings.REGION_ID,
        vote_data=vote,
        quorum_threshold=challenge.quorum_threshold,
        quorum_regions=challenge.quorum_regions,
        url=challenge.url,
        redis_client=redis_client,
    )

    return True


async def run_quorum_consumer() -> None:
    connection = await get_rabbitmq_connection()
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=10)
    queue = await setup_quorum_topology(channel, settings.REGION_ID)

    redis_client = get_redis_client()

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            try:
                payload = json.loads(message.body.decode("utf-8"))
            except Exception as exc:
                CHECKER_PROCESSING_ERRORS_TOTAL.inc()
                logger.error("Poison challenge message JSON decode failed: %s", exc)
                async with message.process(requeue=False):
                    pass
                continue

            async with message.process(requeue=False):
                try:
                    await process_quorum_challenge(payload, redis_client)
                except Exception as exc:
                    CHECKER_PROCESSING_ERRORS_TOTAL.inc()
                    logger.error("Error processing quorum challenge: %s", exc, exc_info=True)
