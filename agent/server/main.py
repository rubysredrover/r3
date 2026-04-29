"""FastAPI server for Ruby's Red Rover v2.

Serves the demo web UI, broadcasts orchestrator reasoning events over
WebSocket, and exposes a POST /demo/play endpoint that synthesizes Ruby's
voice for a given utterance and kicks off the agent loop in the background.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from server import orchestrator
from server.tools import clone_voice, phone, bolo

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="Ruby's Red Rover v2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://localhost:3000",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- WebSocket broadcast manager ----------


class ConnectionManager:
    def __init__(self) -> None:
        self.active: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self.active.append(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            if ws in self.active:
                self.active.remove(ws)

    async def broadcast(self, event: dict[str, Any]) -> None:
        """Send an event to all connected clients. Best-effort, drops dead clients."""
        payload = {**event, "ts": time.time()}
        message = json.dumps(payload)
        async with self._lock:
            dead: list[WebSocket] = []
            for ws in self.active:
                try:
                    await ws.send_text(message)
                except Exception as exc:
                    logger.warning("dropping dead websocket: %s", exc)
                    dead.append(ws)
            for ws in dead:
                self.active.remove(ws)


manager = ConnectionManager()


# ---------- Live-call approval registry ----------
# When the orchestrator detects "ask my mom" mid-call, it waits on a Future
# keyed by the call_id. Mom tapping Approve / Decline on the panel resolves it.
pending_approvals: dict[str, asyncio.Future] = {}


def register_pending_approval(call_id: str) -> asyncio.Future:
    fut: asyncio.Future = asyncio.get_event_loop().create_future()
    pending_approvals[call_id] = fut
    return fut


def resolve_pending_approval(call_id: str, decision: dict[str, Any]) -> bool:
    fut = pending_approvals.pop(call_id, None)
    if fut and not fut.done():
        fut.set_result(decision)
        return True
    return False


# ---------- Routes ----------


@app.get("/")
async def root() -> FileResponse:
    index = WEB_DIR / "index.html"
    if not index.exists():
        return JSONResponse(
            {"error": f"index.html not found at {index}"}, status_code=404
        )
    return FileResponse(str(index))


@app.get("/static/{path:path}")
async def static_files(path: str) -> FileResponse:
    target = (WEB_DIR / path).resolve()
    # Prevent path traversal
    if not str(target).startswith(str(WEB_DIR.resolve())):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    if not target.exists() or not target.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(str(target))


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        while True:
            # Keepalive: we don't expect messages from the client, but read to
            # detect disconnects.
            await ws.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(ws)
    except Exception as exc:
        logger.warning("ws error: %s", exc)
        await manager.disconnect(ws)


class DemoPlayRequest(BaseModel):
    text: str


@app.post("/demo/play")
async def demo_play(req: DemoPlayRequest, background: BackgroundTasks) -> dict[str, Any]:
    """Synthesize Ruby's voice for the given text, then kick off the agent loop."""
    job_id = str(uuid.uuid4())
    logger.info("demo/play job_id=%s text=%r", job_id, req.text)

    # Synthesize via cloned voice
    try:
        audio_bytes = await clone_voice.synthesize_as_ruby(req.text)
    except Exception as exc:
        logger.exception("clone_voice.synthesize_as_ruby failed")
        return JSONResponse(
            {"job_id": job_id, "error": f"synthesize failed: {exc}"},
            status_code=500,
        )

    # Save to a temp file
    tmp = tempfile.NamedTemporaryFile(
        prefix=f"ruby_{job_id}_", suffix=".wav", delete=False
    )
    try:
        tmp.write(audio_bytes if isinstance(audio_bytes, (bytes, bytearray)) else b"")
    finally:
        tmp.close()

    audio_path = tmp.name

    # Fire and forget
    async def _run() -> None:
        try:
            await orchestrator.run_agent(audio_path, manager.broadcast)
        except Exception as exc:
            logger.exception("orchestrator.run_agent failed")
            await manager.broadcast(
                {"type": "fatal", "payload": {"job_id": job_id, "error": str(exc)}}
            )

    background.add_task(_run)
    return {"job_id": job_id, "audio_path": audio_path}


class DemoApproveRequest(BaseModel):
    amount: float
    call_id: str | None = None


@app.post("/demo/approve")
async def demo_approve(req: DemoApproveRequest, background: BackgroundTasks) -> dict[str, Any]:
    """Mom tapped Approve on the approval-needed notification.

    Fires a fresh notification chain on the panel: Mom approved → agent calls
    Folino's back → order placed → audited. For the demo this is theatre on
    top of the existing call (we don't actually re-dial), but it makes the
    full trust loop visible: grant → escalation → approval → action.
    """
    logger.info("demo/approve amount=%s call_id=%s", req.amount, req.call_id)
    amount = round(float(req.amount), 2)

    # If there's a live call waiting for this approval, resolve its Future.
    # The orchestrator's mid-call watcher will then inject the answer via
    # Vapi's controlUrl. No callback needed in that case.
    if req.call_id and resolve_pending_approval(req.call_id, {"approved": True, "amount": amount}):
        await manager.broadcast({
            "event": "mom_notification",
            "data": {
                "message": f"You approved ${amount:.2f} — Chantal is finishing the call now.",
                "kind": "approved",
                "details": {"amount": amount, "call_id": req.call_id, "live": True},
            },
        })
        return {"ok": True, "amount": amount, "mode": "live"}

    async def _run() -> None:
        try:
            # 1) Mom's approval action — show clearly on the panel
            await manager.broadcast({
                "event": "mom_notification",
                "data": {
                    "message": f"You approved ${amount:.2f} — Chantal is calling Folino's back now.",
                    "kind": "approved",
                    "details": {"amount": amount, "call_id": req.call_id},
                },
            })

            # 2) Resolve target phone (Folino's, from mom's grant)
            mom_grant = await bolo.get_grants(grantor="@mom", grantee="@ruby", widget="mars")
            scopes = mom_grant.get("scopes", {})
            directory = scopes.get("vendors:directory", {})
            target_phone = (
                os.environ.get("VAPI_TARGET_PHONE")
                or directory.get("folinos", {}).get("phone")
                or "+15555550199"
            )
            card = scopes.get("payment:card", {})
            addr = scopes.get("delivery:address", {})

            address_block = (
                f"  Street (give first):  {addr.get('line1', '')}\n"
                f"  City (only if asked): {addr.get('city', '')}\n"
                f"  State (if asked):     {addr.get('state', '')}\n"
                f"  ZIP (if asked):       {addr.get('zip', '')}\n"
                f"  Name on order:        {addr.get('name', 'Ruby Cossette')}\n"
                f"  Callback phone:       {addr.get('callback_phone', '')}\n"
                f"  Delivery notes:       {addr.get('delivery_notes', '')}"
            )
            card_number = card.get("number", "")
            card_chunked = " ".join(card_number[i:i+4] for i in range(0, len(card_number), 4))
            card_block = (
                f"  Brand:    {card.get('brand', 'Visa')}\n"
                f"  Number:   {card_chunked}\n"
                f"  Exp:      {card.get('exp', '')}\n"
                f"  CVC:      {card.get('cvc', '')}\n"
                f"  ZIP:      {card.get('zip', '')}\n"
                f"  Name:     {card.get('name_on_card', '')}"
            )

            # 3) Build callback prompt — Chantal opens with "calling back, mom said yes"
            cb_first_message = (
                f"Hi! Yeah it's me again from before — I just talked to my mom and "
                f"she said it's okay to do the ${amount:.2f}. Want to go ahead with "
                f"the order?"
            )
            cb_system_prompt = (
                "You're calling Folino's back after a quick break to check with "
                "your mom. She approved the higher total. Be warm and brief. Open "
                "by acknowledging the earlier call and confirming the new approved "
                f"amount of ${amount:.2f}. Then proceed normally:\n"
                "\n"
                "ORDER: One large pepperoni for delivery (or whatever was being\n"
                "discussed). Confirm the order is still on the table.\n"
                "\n"
                "DELIVERY ADDRESS (give street first, then more if they ask):\n"
                f"{address_block}\n"
                "\n"
                "PAYMENT (read card # in groups of 4 with pauses; only give exp,\n"
                "CVC, ZIP individually when they ask):\n"
                f"{card_block}\n"
                "\n"
                f"You're approved up to ${amount:.2f}, no need to negotiate further.\n"
                "Confirm the ETA, thank them warmly, and end the call."
            )

            # 4) Place the actual callback
            await manager.broadcast({
                "event": "calling",
                "data": {"vendor": "Folino's", "number": "+1 (646) ••• ••81"},
            })
            await manager.broadcast({
                "event": "mom_notification",
                "data": {
                    "message": f"Calling Folino's back — confirming new total ${amount:.2f}.",
                    "kind": "calling",
                    "details": {"amount": amount},
                },
            })

            cb_result = await phone.place_call(
                phone_number=target_phone,
                system_prompt=cb_system_prompt,
                first_message=cb_first_message,
            )
            cb_call_id = cb_result.get("call_id") if isinstance(cb_result, dict) else None
            cb_failed = isinstance(cb_result, dict) and cb_result.get("vapi_failed")

            if cb_failed or not cb_call_id or cb_call_id == "mock-call-123":
                # Real call couldn't be placed — fall back to a synthetic done
                await manager.broadcast({
                    "event": "mom_notification",
                    "data": {
                        "message": f"Order placed (simulated): 1 large pepperoni · ETA 35 min · ${amount:.2f}",
                        "kind": "placed",
                        "details": {"amount": amount, "eta_min": 35},
                    },
                })
                await manager.broadcast({
                    "event": "done",
                    "data": {
                        "summary": (
                            f"Approved by Mom. Callback was simulated "
                            f"({cb_result.get('error', 'no key')}). "
                            f"$${amount:.2f}, ETA 35 min."
                        ),
                        "outcome": "success",
                    },
                })
                return

            # 5) Real call placed — poll until ended
            async def _on_status(info: dict[str, Any]) -> None:
                await manager.broadcast({
                    "event": "call_status",
                    "data": {
                        "status": info.get("status"),
                        "endedReason": info.get("endedReason"),
                    },
                })

            final_state = await phone.poll_until_ended(cb_call_id, on_status=_on_status)
            ended_reason = final_state.get("endedReason") or ""

            if ended_reason in ("customer-ended-call", "assistant-ended-call", ""):
                await manager.broadcast({
                    "event": "mom_notification",
                    "data": {
                        "message": f"Order placed: 1 large pepperoni · ETA 35 min · ${amount:.2f}",
                        "kind": "placed",
                        "details": {"amount": amount, "eta_min": 35},
                    },
                })
                await manager.broadcast({
                    "event": "mom_notification",
                    "data": {
                        "message": f"Charged Visa •4242: ${amount:.2f} · audit logged to Bolo",
                        "kind": "audited",
                        "details": {"last4": "4242", "amount": amount},
                    },
                })
                await manager.broadcast({
                    "event": "done",
                    "data": {
                        "summary": f"Approved by Mom. Pepperoni from Folino's, ${amount:.2f}, ETA 35 min — placed in Chantal's voice.",
                        "outcome": "success",
                    },
                })
            else:
                await manager.broadcast({
                    "event": "mom_notification",
                    "data": {
                        "message": f"Callback to Folino's didn't complete ({ended_reason}). No order placed.",
                        "kind": "call_failed",
                        "details": {"ended_reason": ended_reason, "call_id": cb_call_id},
                    },
                })
                await manager.broadcast({
                    "event": "done",
                    "data": {
                        "summary": f"Mom approved, but the callback ended without an order ({ended_reason}).",
                        "outcome": "call_failed",
                    },
                })

        except Exception as exc:
            logger.exception("demo/approve flow failed: %s", exc)

    background.add_task(_run)
    return {"ok": True, "amount": amount}


class DemoDeferRequest(BaseModel):
    call_id: str | None = None
    amount: float | None = None


@app.post("/demo/defer")
async def demo_defer(req: DemoDeferRequest) -> dict[str, Any]:
    """Mom tapped 'Call back later' — Chantal politely ends the call so Mom
    can decide at her own pace. Mom can still tap Approve later, which falls
    through to the regular callback flow (fresh call to Folino's).
    """
    logger.info("demo/defer call_id=%s", req.call_id)
    if req.call_id and resolve_pending_approval(req.call_id, {"approved": False, "deferred": True}):
        await manager.broadcast({
            "event": "mom_notification",
            "data": {
                "message": "You'll decide later — Chantal will tell Folino's to expect a callback.",
                "kind": "deferred",
                "details": {"call_id": req.call_id, "amount": req.amount},
            },
        })
        # Show a fresh approval card (without Defer this time) so Mom can still
        # come back and approve / decline at her leisure. The old call_id is
        # gone so an eventual Approve falls through to the callback flow.
        await manager.broadcast({
            "event": "mom_notification",
            "data": {
                "message": (
                    f"Take your time — when you're ready, tap Approve and "
                    f"Chantal will call Folino's back at "
                    f"${(req.amount or 0):.2f}."
                ),
                "kind": "approval_request",
                "details": {
                    "requested_amount": req.amount,
                    "call_id": None,  # no live call now
                    "live": False,
                    "no_defer": True,  # tells UI not to show Defer button
                },
            },
        })
        return {"ok": True, "mode": "defer"}
    return {"ok": False, "error": "no live call to defer"}


class DemoDeclineRequest(BaseModel):
    call_id: str | None = None
    reason: str | None = None


@app.post("/demo/decline")
async def demo_decline(req: DemoDeclineRequest) -> dict[str, Any]:
    """Mom tapped Decline on the approval-needed notification."""
    logger.info("demo/decline call_id=%s", req.call_id)
    if req.call_id and resolve_pending_approval(req.call_id, {"approved": False, "reason": req.reason or "declined"}):
        await manager.broadcast({
            "event": "mom_notification",
            "data": {
                "message": "You declined. Chantal will politely end the call.",
                "kind": "call_failed",
                "details": {"call_id": req.call_id, "live": True},
            },
        })
        return {"ok": True, "mode": "live"}
    # Non-live decline (call already ended) — just show a record
    await manager.broadcast({
        "event": "mom_notification",
        "data": {
            "message": "You declined the bump. No order will be placed tonight.",
            "kind": "call_failed",
            "details": {},
        },
    })
    await manager.broadcast({
        "event": "done",
        "data": {"summary": "Mom declined the bump. No order placed.", "outcome": "call_failed"},
    })
    return {"ok": True, "mode": "post_call"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
