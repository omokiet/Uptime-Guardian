import asyncio
from datetime import datetime, timezone
import json
import logging
from typing import Dict, Optional, Set
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from services.common.redis_client import get_redis_client
from services.common.security import decode_access_token

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket"])


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self.socket_queues: Dict[WebSocket, asyncio.Queue] = {}
        self.socket_writers: Dict[WebSocket, asyncio.Task] = {}
        self.user_listeners: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, user_id: str) -> None:
        async with self._lock:
            if user_id not in self.active_connections:
                self.active_connections[user_id] = set()
            self.active_connections[user_id].add(websocket)

            # Bounded queue with drop_oldest policy to prevent slow consumer buffer bloat
            queue: asyncio.Queue = asyncio.Queue(maxsize=100)
            self.socket_queues[websocket] = queue
            writer_task = asyncio.create_task(self._socket_writer(websocket, queue))
            self.socket_writers[websocket] = writer_task

            # Multiplex single Redis Pub/Sub listener per unique user_id
            if user_id not in self.user_listeners:
                listener_task = asyncio.create_task(self._redis_listener(user_id))
                self.user_listeners[user_id] = listener_task

    async def disconnect(self, websocket: WebSocket, user_id: str) -> None:
        async with self._lock:
            if user_id in self.active_connections:
                self.active_connections[user_id].discard(websocket)
                if len(self.active_connections[user_id]) == 0:
                    del self.active_connections[user_id]
                    listener = self.user_listeners.pop(user_id, None)
                    if listener and not listener.done():
                        listener.cancel()

            self.socket_queues.pop(websocket, None)
            writer = self.socket_writers.pop(websocket, None)
            if writer and not writer.done():
                writer.cancel()

    async def broadcast_to_user(self, user_id: str, message: dict) -> None:
        async with self._lock:
            sockets = list(self.active_connections.get(user_id, []))

        for ws in sockets:
            q = self.socket_queues.get(ws)
            if q:
                if q.full():
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                try:
                    q.put_nowait(message)
                except asyncio.QueueFull:
                    pass

    async def _socket_writer(self, websocket: WebSocket, queue: asyncio.Queue) -> None:
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_json(msg)
            except asyncio.TimeoutError:
                try:
                    await websocket.send_json({"event": "ping"})
                except Exception:
                    break
            except asyncio.CancelledError:
                break
            except Exception:
                break

    async def _redis_listener(self, user_id: str) -> None:
        channel_name = f"telemetry:user:{user_id}"

        while True:
            async with self._lock:
                if user_id not in self.active_connections:
                    break

            redis_client = get_redis_client()
            pubsub = redis_client.pubsub()
            try:
                await pubsub.subscribe(channel_name)
                async for item in pubsub.listen():
                    if item and item.get("type") == "message":
                        raw_data = item.get("data")
                        if raw_data:
                            if isinstance(raw_data, bytes):
                                raw_data = raw_data.decode("utf-8")
                            payload = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
                            await self.broadcast_to_user(user_id, payload)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Redis Pub/Sub error on %s, reconnecting: %s", channel_name, exc)
                await asyncio.sleep(1.0)
            finally:
                try:
                    await pubsub.unsubscribe(channel_name)
                    await pubsub.close()
                except Exception:
                    pass


manager = ConnectionManager()


@router.websocket("/ws/telemetry")
async def websocket_telemetry(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
) -> None:
    await websocket.accept()
    auth_token = token

    if not auth_token:
        try:
            raw_frame = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
            frame = json.loads(raw_frame)
            if isinstance(frame, dict) and frame.get("action") == "auth":
                auth_token = frame.get("token")
        except (asyncio.TimeoutError, Exception):
            await websocket.close(code=1008, reason="Authentication timeout")
            return

    if not auth_token:
        await websocket.close(code=1008, reason="Missing authentication token")
        return

    payload = decode_access_token(auth_token)
    if not payload or not payload.get("sub"):
        await websocket.close(code=1008, reason="Invalid or expired token")
        return

    user_id = str(payload.get("sub"))
    await manager.connect(websocket, user_id)
    await websocket.send_json({"event": "connected", "user_id": user_id})

    try:
        while True:
            msg_text = await websocket.receive_text()
            try:
                req = json.loads(msg_text)
                if isinstance(req, dict) and req.get("action") == "ping":
                    await websocket.send_json({
                        "event": "pong",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
            except Exception:
                pass
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("WebSocket client disconnected: %s", exc)
    finally:
        await manager.disconnect(websocket, user_id)
