import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from services.alerter.quorum_engine import (
    evaluate_quorum_votes,
    record_vote_and_evaluate,
    resolve_quorum_on_timeout,
)
from services.alerter.state_machine import handle_alert_event
from services.common.models import CheckResult, Monitor, User


def test_evaluate_quorum_votes_logic() -> None:
    regions = ["vn-han", "sg-sin", "us-iad"]
    threshold = 2

    # 1 FAIL, 0 PASS -> PENDING
    votes_1 = {
        "vn-han": {"status": "FAIL", "status_code": 500, "response_time_ms": 100},
    }
    decision, reason = evaluate_quorum_votes(votes_1, threshold, regions, is_timeout=False)
    assert decision == "PENDING"

    # 2 FAIL -> OUTAGE_CONFIRMED immediately
    votes_2_fail = {
        "vn-han": {"status": "FAIL", "status_code": 500, "response_time_ms": 100},
        "sg-sin": {"status": "FAIL", "status_code": 504, "response_time_ms": 5000},
    }
    decision, reason = evaluate_quorum_votes(votes_2_fail, threshold, regions, is_timeout=False)
    assert decision == "OUTAGE_CONFIRMED"
    assert "2/3 regions failed" in reason
    # Ensure no emojis in reason
    assert "🚨" not in reason

    # 2 PASS -> SUPPRESSED immediately (impossible to reach 2 fails)
    votes_2_pass = {
        "vn-han": {"status": "FAIL", "status_code": 500, "response_time_ms": 100},
        "sg-sin": {"status": "PASS", "status_code": 200, "response_time_ms": 50},
        "us-iad": {"status": "PASS", "status_code": 200, "response_time_ms": 60},
    }
    decision, reason = evaluate_quorum_votes(votes_2_pass, threshold, regions, is_timeout=False)
    assert decision == "SUPPRESSED"
    assert "Quorum suppressed alert" in reason

    # 1 FAIL, 1 PASS on timeout -> SUPPRESSED (threshold 2 not reached)
    votes_tie = {
        "vn-han": {"status": "FAIL", "status_code": 500, "response_time_ms": 100},
        "sg-sin": {"status": "PASS", "status_code": 200, "response_time_ms": 50},
    }
    decision, reason = evaluate_quorum_votes(votes_tie, threshold, regions, is_timeout=True)
    assert decision == "SUPPRESSED"


@pytest.mark.asyncio
async def test_record_vote_and_evaluate_fast_outage_confirmation() -> None:
    mock_redis = AsyncMock()
    pipe = MagicMock()
    pipe.execute = AsyncMock()
    mock_redis.pipeline = MagicMock(return_value=pipe)

    challenge_id = str(uuid.uuid4())
    monitor_id = str(uuid.uuid4())
    regions = ["vn-han", "sg-sin", "us-iad"]

    # Existing votes in Redis hash: vn-han already voted FAIL
    mock_redis.hgetall = AsyncMock(return_value={
        "vn-han": json.dumps({"status": "FAIL", "status_code": 500, "response_time_ms": 100}),
        "sg-sin": json.dumps({"status": "FAIL", "status_code": 502, "response_time_ms": 200}),
    })
    # Atomic decision lock succeeds
    mock_redis.hsetnx = AsyncMock(return_value=1)

    mock_publish = AsyncMock()
    with patch("services.alerter.quorum_engine.publish_message", mock_publish):
        decision = await record_vote_and_evaluate(
            challenge_id=challenge_id,
            monitor_id=monitor_id,
            initiator_job_id=str(uuid.uuid4()),
            region_id="sg-sin",
            vote_data={"status": "FAIL", "status_code": 502, "response_time_ms": 200},
            quorum_threshold=2,
            quorum_regions=regions,
            url="https://api.example.com",
            redis_client=mock_redis,
        )

        assert decision == "OUTAGE_CONFIRMED"
        assert mock_redis.hsetnx.called
        assert mock_publish.called
        event_payload = mock_publish.call_args[0][1]
        assert event_payload["is_success"] is False
        assert event_payload["quorum_confirmed"] is True
        assert "2/3 regions failed" in event_payload["error_message"]
        # Ensure no emojis in error_message
        assert "🚨" not in event_payload["error_message"]


@pytest.mark.asyncio
async def test_record_vote_atomic_guard_prevents_duplicate_publish() -> None:
    mock_redis = AsyncMock()
    pipe = MagicMock()
    pipe.execute = AsyncMock()
    mock_redis.pipeline = MagicMock(return_value=pipe)

    mock_redis.hgetall = AsyncMock(return_value={
        "vn-han": json.dumps({"status": "FAIL", "status_code": 500}),
        "sg-sin": json.dumps({"status": "FAIL", "status_code": 502}),
    })
    # Another worker already set the decision!
    mock_redis.hsetnx = AsyncMock(return_value=0)

    mock_publish = AsyncMock()
    with patch("services.alerter.quorum_engine.publish_message", mock_publish):
        decision = await record_vote_and_evaluate(
            challenge_id=str(uuid.uuid4()),
            monitor_id=str(uuid.uuid4()),
            initiator_job_id=str(uuid.uuid4()),
            region_id="us-iad",
            vote_data={"status": "FAIL", "status_code": 504},
            quorum_threshold=2,
            quorum_regions=["vn-han", "sg-sin", "us-iad"],
            url="https://api.example.com",
            redis_client=mock_redis,
        )
        assert decision == "OUTAGE_CONFIRMED"
        # Duplicate publish must be blocked!
        assert not mock_publish.called


@pytest.mark.asyncio
async def test_suppressed_quorum_updates_db_is_suppressed(db_session: AsyncSession) -> None:
    user = User(email="suppress_db@example.com", password_hash="hash")
    db_session.add(user)
    await db_session.flush()

    monitor = Monitor(
        user_id=user.id,
        name="Suppress DB Target",
        url="https://1.1.1.1/health",
        quorum_enabled=True,
    )
    db_session.add(monitor)
    await db_session.flush()

    initiator_job_id = uuid.uuid4()
    cr = CheckResult(
        monitor_id=monitor.id,
        job_id=initiator_job_id,
        status_code=500,
        response_time_ms=100,
        is_success=False,
        region_id="vn-han",
        is_suppressed=False,
    )
    db_session.add(cr)
    await db_session.commit()

    mock_redis = AsyncMock()
    pipe = MagicMock()
    pipe.execute = AsyncMock()
    mock_redis.pipeline = MagicMock(return_value=pipe)

    # 2 PASS votes -> Quorum suppresses
    mock_redis.hgetall = AsyncMock(return_value={
        "vn-han": json.dumps({"status": "FAIL", "status_code": 500}),
        "sg-sin": json.dumps({"status": "PASS", "status_code": 200}),
        "us-iad": json.dumps({"status": "PASS", "status_code": 200}),
    })
    mock_redis.hsetnx = AsyncMock(return_value=1)

    with patch("services.alerter.quorum_engine.AsyncSessionLocal", return_value=db_session):
        decision = await record_vote_and_evaluate(
            challenge_id=str(uuid.uuid4()),
            monitor_id=str(monitor.id),
            initiator_job_id=str(initiator_job_id),
            region_id="us-iad",
            vote_data={"status": "PASS", "status_code": 200},
            quorum_threshold=2,
            quorum_regions=["vn-han", "sg-sin", "us-iad"],
            url="https://1.1.1.1/health",
            redis_client=mock_redis,
        )

        assert decision == "SUPPRESSED"
        res = await db_session.execute(select(CheckResult).where(CheckResult.job_id == initiator_job_id))
        cr_updated = res.scalar_one()
        assert cr_updated.is_suppressed is True


@pytest.mark.asyncio
async def test_state_machine_transitions_directly_to_down_on_quorum(db_session: AsyncSession) -> None:
    user = User(email="fsm_quorum@example.com", password_hash="hash")
    db_session.add(user)
    await db_session.flush()

    # consecutive_threshold=3, but quorum_confirmed should transition directly to DOWN
    monitor = Monitor(
        user_id=user.id,
        name="FSM Quorum Target",
        url="https://1.1.1.1/health",
        consecutive_threshold=3,
        current_status="UP",
        quorum_enabled=True,
    )
    db_session.add(monitor)
    await db_session.commit()

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.eval = AsyncMock(return_value=1)
    mock_redis.hgetall = AsyncMock(return_value={
        "status": "UP",
        "consecutive_fails": "0",
        "cooldown_until": "0",
    })

    event = {
        "job_id": str(uuid.uuid4()),
        "monitor_id": str(monitor.id),
        "url": monitor.url,
        "is_success": False,
        "error_message": "Quorum confirmed outage (2/3 regions failed: vn-han, sg-sin)",
        "quorum_confirmed": True,
    }

    mock_notify = AsyncMock()
    with patch("services.alerter.state_machine.get_redis_client", return_value=mock_redis), \
         patch("services.alerter.state_machine.notify_channels", mock_notify), \
         patch("services.alerter.state_machine.AsyncSessionLocal", return_value=db_session):

        await handle_alert_event(event)

        # Monitor state in DB must be DOWN immediately
        res = await db_session.execute(select(Monitor).where(Monitor.id == monitor.id))
        mon_updated = res.scalar_one()
        assert mon_updated.current_status == "DOWN"
        assert mock_notify.called
        notify_msg = mock_notify.call_args[0][2]
        assert "2/3 regions failed" in notify_msg


@pytest.mark.asyncio
async def test_resolve_quorum_on_timeout_suppresses_alert(db_session: AsyncSession) -> None:
    user = User(email="timeout_db@example.com", password_hash="hash")
    db_session.add(user)
    await db_session.flush()

    monitor = Monitor(
        user_id=user.id,
        name="Timeout DB Target",
        url="https://1.1.1.1/health",
        quorum_enabled=True,
    )
    db_session.add(monitor)
    await db_session.flush()

    initiator_job_id = uuid.uuid4()
    cr = CheckResult(
        monitor_id=monitor.id,
        job_id=initiator_job_id,
        status_code=500,
        response_time_ms=100,
        is_success=False,
        region_id="vn-han",
        is_suppressed=False,
    )
    db_session.add(cr)
    await db_session.commit()

    mock_redis = AsyncMock()
    mock_redis.delete = AsyncMock()
    # Only 1 FAIL recorded, threshold is 2
    mock_redis.hgetall = AsyncMock(return_value={
        "vn-han": json.dumps({"status": "FAIL", "status_code": 500}),
    })
    mock_redis.hsetnx = AsyncMock(return_value=1)

    with patch("services.alerter.quorum_engine.AsyncSessionLocal", return_value=db_session):
        decision = await resolve_quorum_on_timeout(
            challenge_id=str(uuid.uuid4()),
            monitor_id=str(monitor.id),
            initiator_job_id=str(initiator_job_id),
            quorum_threshold=2,
            quorum_regions=["vn-han", "sg-sin", "us-iad"],
            url="https://1.1.1.1/health",
            timeout_seconds=0.01,
            redis_client=mock_redis,
        )

        assert decision == "SUPPRESSED"
        res = await db_session.execute(select(CheckResult).where(CheckResult.job_id == initiator_job_id))
        cr_updated = res.scalar_one()
        assert cr_updated.is_suppressed is True
        mock_redis.delete.assert_called_once_with(f"quorum:active:{monitor.id}")
