from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from job_agent.db import (
    approve_job_review,
    ignore_job_review,
    init_db,
    list_admin_jobs,
    list_job_reviews,
    list_source_sync_logs,
    list_source_sync_state,
)
from job_agent.rag import sync_index
from job_agent.resume import RESUME_DIR, read_resume, resolve_resume_name
from job_agent.sessions import create_session, delete_session, init_sessions_db, list_sessions, touch_session
from job_agent.web_agent import web_agent

STATIC_DIR = Path(__file__).resolve().parent / "static"
ALLOWED_RESUME_SUFFIXES = {".pdf", ".docx", ".txt"}
MAX_RESUME_BYTES = 8 * 1024 * 1024


class SessionCreate(BaseModel):
    name: str = "新对话"
    user_id: str = "local-user"


class ChatRequest(BaseModel):
    thread_id: str
    message: str
    resume_name: str | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    init_sessions_db()
    RESUME_DIR.mkdir(parents=True, exist_ok=True)
    await web_agent.init()
    yield
    await web_agent.close()


app = FastAPI(title="Agent-JobHunting", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/admin")
async def admin():
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/resumes")
async def resumes():
    files = [
        path.name
        for path in RESUME_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in ALLOWED_RESUME_SUFFIXES
    ]
    return {"resume_dir": str(RESUME_DIR), "files": sorted(files)}


@app.get("/api/admin/sources")
async def admin_sources():
    return {"sources": list_source_sync_state()}


@app.get("/api/admin/sync-logs")
async def admin_sync_logs(limit: int = 100):
    return {"logs": list_source_sync_logs(limit=max(1, min(limit, 500)))}


@app.get("/api/admin/jobs")
async def admin_jobs(limit: int = 200):
    return {"jobs": list_admin_jobs(limit=max(1, min(limit, 1000)))}


@app.get("/api/admin/reviews")
async def admin_reviews(status: str = "pending", limit: int = 200):
    if status not in {"pending", "approved", "ignored", "all"}:
        raise HTTPException(status_code=400, detail="审核状态无效")
    return {
        "reviews": list_job_reviews(
            status=None if status == "all" else status,
            limit=max(1, min(limit, 1000)),
        )
    }


@app.post("/api/admin/reviews/{job_id}/approve")
async def admin_approve_review(job_id: str):
    try:
        approved_id = approve_job_review(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    sync_index([approved_id], [])
    return {"success": True, "job_id": approved_id, "status": "approved"}


@app.post("/api/admin/reviews/{job_id}/ignore")
async def admin_ignore_review(job_id: str):
    try:
        ignored_id = ignore_job_review(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"success": True, "job_id": ignored_id, "status": "ignored"}


@app.post("/api/resumes/upload")
async def upload_resume(file: UploadFile = File(...)):
    original_name = (file.filename or "").replace("\\", "/")
    filename = Path(original_name).name
    suffix = Path(filename).suffix.lower()
    if not filename or suffix not in ALLOWED_RESUME_SUFFIXES:
        raise HTTPException(status_code=400, detail="仅支持 PDF、DOCX 和 TXT 简历")

    RESUME_DIR.mkdir(parents=True, exist_ok=True)
    destination = RESUME_DIR / filename
    temporary = RESUME_DIR / f".{uuid4().hex}.upload{suffix}"
    size = 0
    try:
        with temporary.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_RESUME_BYTES:
                    raise HTTPException(status_code=413, detail="简历文件不能超过 8 MB")
                output.write(chunk)
        read_resume(str(temporary))
        temporary.replace(destination)
    except HTTPException:
        temporary.unlink(missing_ok=True)
        raise
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"无法解析简历文件：{exc}") from exc
    finally:
        await file.close()

    return {"filename": filename, "size": size}


@app.delete("/api/resumes/{filename}")
async def delete_resume(filename: str):
    safe_name = Path(filename.replace("\\", "/")).name
    suffix = Path(safe_name).suffix.lower()
    if not safe_name or safe_name != filename or suffix not in ALLOWED_RESUME_SUFFIXES:
        raise HTTPException(status_code=400, detail="简历文件名无效")

    path = RESUME_DIR / safe_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="简历不存在")
    path.unlink()
    return {"success": True, "filename": safe_name}


@app.post("/api/sessions")
async def new_session(request: SessionCreate):
    return create_session(user_id=request.user_id, name=request.name)


@app.get("/api/sessions")
async def sessions(user_id: str = "local-user"):
    return list_sessions(user_id=user_id)


@app.delete("/api/sessions/{thread_id}")
async def remove_session(thread_id: str):
    if not delete_session(thread_id):
        raise HTTPException(status_code=404, detail="Session not found")
    await web_agent.delete_thread(thread_id)
    return {"success": True}


@app.get("/api/sessions/{thread_id}/messages")
async def session_messages(thread_id: str):
    return {"messages": await web_agent.messages(thread_id)}


@app.post("/api/chat/send")
async def send_chat(request: ChatRequest):
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息不能为空")
    resume_name = request.resume_name.strip() if request.resume_name else None
    if resume_name:
        try:
            resume_name = resolve_resume_name(resume_name).name
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        touch_session(request.thread_id, message=message)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return EventSourceResponse(web_agent.stream(request.thread_id, message, resume_name=resume_name))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("job_agent.web:app", host="127.0.0.1", port=8001, reload=True)
