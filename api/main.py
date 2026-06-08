"""
PromoLens AI — FastAPI backend for Cloud Run.
Exposes POST /chat -> runs the ADK orchestrator -> returns the copilot's answer.
"""
import os, sys, uuid
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agents.agent import root_agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

APP = "promolens"
session_service = InMemorySessionService()
runner = Runner(agent=root_agent, app_name=APP, session_service=session_service)

app = FastAPI(title="PromoLens AI")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class ChatIn(BaseModel):
    message: str
    session_id: str | None = None


def _ensure_session(user_id: str, session_id: str):
    # ADK session creation is sync in current releases; guard for async variants.
    try:
        session_service.create_session(app_name=APP, user_id=user_id, session_id=session_id)
    except Exception:
        import asyncio
        try:
            asyncio.get_event_loop().run_until_complete(
                session_service.create_session(app_name=APP, user_id=user_id, session_id=session_id))
        except Exception:
            pass


@app.get("/healthz")
def healthz():
    return {"ok": True, "backend": os.environ.get("PROMOLENS_BACKEND", "csv")}


@app.post("/chat")
def chat(inp: ChatIn):
    user_id = "demo-user"
    session_id = inp.session_id or f"s-{uuid.uuid4().hex[:8]}"
    _ensure_session(user_id, session_id)
    msg = types.Content(role="user", parts=[types.Part(text=inp.message)])
    final = ""
    for event in runner.run(user_id=user_id, session_id=session_id, new_message=msg):
        if event.is_final_response() and event.content and event.content.parts:
            final = "".join(p.text or "" for p in event.content.parts)
    return {"session_id": session_id, "answer": final or "(no response)"}
