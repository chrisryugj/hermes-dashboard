"""
Hermes Dashboard Backend API
~/.hermes/dashboard/api.py

api_server.py의 aiohttp app에 대시보드 라우트를 등록하는 플러그인.
"""

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

try:
    from aiohttp import web
except ImportError:
    web = None  # type: ignore

HERMES_HOME = Path(os.getenv("HERMES_HOME", Path.home() / ".hermes"))
DASHBOARD_DIR = HERMES_HOME / "dashboard"

# 시크릿 마스킹: 이 패턴이 키 이름에 포함되면 자동 마스킹
_SECRET_PATTERNS = re.compile(r'TOKEN|KEY|SECRET|PASSWORD|CREDENTIAL', re.IGNORECASE)
_SAFE_NAME = re.compile(r'^[A-Za-z][A-Za-z0-9_]*$')
_SAFE_ID = re.compile(r'^[a-f0-9]{6,20}$')


# ── Atomic File I/O ──

def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {} if yaml else {}
    except Exception:
        return {}


def _write_yaml(path: Path, data: dict) -> None:
    if not yaml:
        raise RuntimeError("PyYAML not installed")
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_json(path: Path) -> Any:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_json(path: Path, data: Any) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_env(path: Path) -> dict:
    result = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result


def _write_env(path: Path, data: dict) -> None:
    lines = [f"{k}={v}" for k, v in data.items()]
    content = "\n".join(lines) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _mask_secret(v: str) -> str:
    if len(v) <= 8:
        return "****"
    return v[:4] + "..." + v[-3:]


def _is_secret_key(k: str) -> bool:
    return bool(_SECRET_PATTERNS.search(k))


def _safe_within(target: Path, parent: Path) -> bool:
    """Verify resolved path is within parent (path traversal prevention)."""
    try:
        target.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


# ── Handlers ──

async def handle_dashboard(request: web.Request) -> web.Response:
    index = DASHBOARD_DIR / "index.html"
    if not index.exists():
        return web.Response(text="Dashboard not found", status=404)
    return web.Response(text=index.read_text(encoding="utf-8"), content_type="text/html", charset="utf-8")


async def handle_overview(request: web.Request) -> web.json_response:
    config = _read_yaml(HERMES_HOME / "config.yaml")
    state = _read_json(HERMES_HOME / "gateway_state.json")
    jobs = _read_json(HERMES_HOME / "cron" / "jobs.json")
    env = _read_env(HERMES_HOME / ".env")
    mcp = config.get("mcp_servers", {})
    skills_dir = HERMES_HOME / "skills"
    skill_count = sum(1 for _ in skills_dir.rglob("SKILL.md")) if skills_dir.exists() else 0
    sessions_dir = HERMES_HOME / "sessions"
    session_count = len(list(sessions_dir.glob("session_*.json"))) if sessions_dir.exists() else 0
    return web.json_response({
        "model": config.get("model", "unknown"),
        "gateway": {
            "pid": state.get("pid"),
            "state": state.get("gateway_state", "unknown"),
            "platforms": state.get("platforms", {}),
            "active_agents": state.get("active_agents", 0),
        },
        "mcp_servers": {name: {"command": s.get("command", ""), "args": s.get("args", [])} for name, s in mcp.items()},
        "cron_jobs": len(jobs.get("jobs", [])),
        "cron_summary": [
            {"id": j["id"], "name": j["name"], "enabled": j.get("enabled", True),
             "last_status": j.get("last_status"), "next_run": j.get("next_run_at"),
             "deliver": j.get("deliver", "local")}
            for j in jobs.get("jobs", [])
        ],
        "skill_count": skill_count,
        "session_count": session_count,
        "telegram": {
            "home_channel": env.get("TELEGRAM_HOME_CHANNEL", ""),
            "allowed_users": env.get("TELEGRAM_ALLOWED_USERS", ""),
        },
    })


async def handle_get_config(request: web.Request) -> web.json_response:
    return web.json_response(_read_yaml(HERMES_HOME / "config.yaml"))


async def handle_set_config(request: web.Request) -> web.json_response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"ok": False, "error": "object expected"}, status=400)
    config = _read_yaml(HERMES_HOME / "config.yaml")
    config.update(body)
    _write_yaml(HERMES_HOME / "config.yaml", config)
    return web.json_response({"ok": True, "restart_needed": True})


async def handle_get_env(request: web.Request) -> web.json_response:
    env = _read_env(HERMES_HOME / ".env")
    masked = {}
    masked_keys = set()
    for k, v in env.items():
        if _is_secret_key(k):
            masked[k] = _mask_secret(v)
            masked_keys.add(k)
        else:
            masked[k] = v
    return web.json_response({"env": masked, "raw_keys": list(env.keys()), "masked_keys": list(masked_keys)})


async def handle_set_env(request: web.Request) -> web.json_response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
    env = _read_env(HERMES_HOME / ".env")
    for k, v in body.items():
        if not _SAFE_NAME.match(k):
            continue
        if "..." in v or "****" in v:
            continue
        env[k] = v
    _write_env(HERMES_HOME / ".env", env)
    return web.json_response({"ok": True})


async def handle_get_mcp(request: web.Request) -> web.json_response:
    return web.json_response(_read_yaml(HERMES_HOME / "config.yaml").get("mcp_servers", {}))


async def handle_set_mcp(request: web.Request) -> web.json_response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"ok": False, "error": "object expected"}, status=400)
    config = _read_yaml(HERMES_HOME / "config.yaml")
    config["mcp_servers"] = body
    _write_yaml(HERMES_HOME / "config.yaml", config)
    return web.json_response({"ok": True, "restart_needed": True})


async def handle_get_soul(request: web.Request) -> web.json_response:
    return web.json_response({"content": _read_text(HERMES_HOME / "SOUL.md")})


async def handle_set_soul(request: web.Request) -> web.json_response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
    _write_text(HERMES_HOME / "SOUL.md", body.get("content", ""))
    return web.json_response({"ok": True})


async def handle_get_skills(request: web.Request) -> web.json_response:
    skills_dir = HERMES_HOME / "skills"
    result = []
    if skills_dir.exists():
        for skill_file in sorted(skills_dir.rglob("SKILL.md")):
            rel = skill_file.relative_to(skills_dir)
            category = str(rel.parent.parent) if len(rel.parts) > 2 else str(rel.parent)
            name = rel.parent.name
            lines = skill_file.read_text(encoding="utf-8", errors="replace").split("\n")
            desc = ""
            for line in lines:
                if line.startswith("description:"):
                    desc = line.split(":", 1)[1].strip().strip('"').strip("'")
                    break
            result.append({"name": name, "category": category, "description": desc, "path": str(rel.parent)})
    return web.json_response(result)


async def handle_get_logs(request: web.Request) -> web.json_response:
    try:
        lines_param = min(max(int(request.query.get("lines", "100")), 1), 5000)
    except (ValueError, TypeError):
        lines_param = 100
    log_file = HERMES_HOME / "logs" / "gateway.log"
    if not log_file.exists():
        return web.json_response({"lines": []})
    all_lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    return web.json_response({"lines": all_lines[-lines_param:]})


async def handle_get_sessions(request: web.Request) -> web.json_response:
    sessions_dir = HERMES_HOME / "sessions"
    result = []
    if sessions_dir.exists():
        files = sorted(sessions_dir.glob("session_*.json"), key=lambda f: f.stat().st_mtime, reverse=True)[:20]
        for f in files:
            st = f.stat()
            result.append({"name": f.stem, "size": st.st_size, "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))})
    return web.json_response(result)


async def handle_restart_gateway(request: web.Request) -> web.json_response:
    try:
        subprocess.run(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/ai.hermes.gateway"], capture_output=True, timeout=10)
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def handle_get_cron_output(request: web.Request) -> web.json_response:
    job_id = request.match_info["job_id"]
    if not _SAFE_ID.match(job_id):
        return web.json_response({"error": "invalid job_id"}, status=400)
    sessions_dir = HERMES_HOME / "sessions"
    outputs = sorted(sessions_dir.glob(f"session_cron_{job_id}_*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not outputs:
        return web.json_response({"output": None})
    return web.json_response({
        "file": outputs[0].name,
        "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(outputs[0].stat().st_mtime)),
        "size": outputs[0].stat().st_size,
    })


async def handle_set_model(request: web.Request) -> web.json_response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
    new_model = body.get("model", "").strip()
    if not new_model or len(new_model) > 100:
        return web.json_response({"ok": False, "error": "model required"}, status=400)
    config = _read_yaml(HERMES_HOME / "config.yaml")
    old_model = config.get("model", "unknown")
    config["model"] = new_model
    _write_yaml(HERMES_HOME / "config.yaml", config)
    return web.json_response({"ok": True, "old": old_model, "new": new_model, "restart_needed": True})


async def handle_get_auth_status(request: web.Request) -> web.json_response:
    auth = _read_json(HERMES_HOME / "auth.json")
    result = {"active_provider": auth.get("active_provider", "unknown"), "providers": {}}
    for name, prov in auth.get("providers", {}).items():
        result["providers"][name] = {
            "has_token": bool(prov.get("access_token") or prov.get("api_key")),
            "last_refresh": prov.get("last_refresh", ""),
            "request_count": prov.get("request_count", 0),
        }
    return web.json_response(result)


async def handle_delete_session(request: web.Request) -> web.json_response:
    name = request.match_info["name"]
    sessions_dir = HERMES_HOME / "sessions"
    target = sessions_dir / f"{name}.json"
    if not _safe_within(target, sessions_dir):
        return web.json_response({"ok": False, "error": "invalid path"}, status=400)
    if target.exists():
        target.unlink()
        return web.json_response({"ok": True})
    return web.json_response({"ok": False, "error": "not found"}, status=404)


async def handle_clear_logs(request: web.Request) -> web.json_response:
    log_file = HERMES_HOME / "logs" / "gateway.log"
    if log_file.exists():
        log_file.write_text("", encoding="utf-8")
    return web.json_response({"ok": True})


async def handle_disk_usage(request: web.Request) -> web.json_response:
    dirs = {
        "sessions": HERMES_HOME / "sessions", "logs": HERMES_HOME / "logs",
        "skills": HERMES_HOME / "skills", "cron": HERMES_HOME / "cron",
        "state.db": HERMES_HOME / "state.db", "response_store.db": HERMES_HOME / "response_store.db",
    }
    result = {}
    for name, path in dirs.items():
        try:
            if path.is_file():
                result[name] = path.stat().st_size
            elif path.is_dir():
                result[name] = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
            else:
                result[name] = 0
        except OSError:
            result[name] = 0
    try:
        result["total"] = sum(f.stat().st_size for f in HERMES_HOME.rglob("*") if f.is_file())
    except OSError:
        result["total"] = 0
    return web.json_response(result)


async def handle_get_skill_detail(request: web.Request) -> web.json_response:
    skill_path = request.match_info["path"]
    skills_dir = HERMES_HOME / "skills"
    skill_file = skills_dir / skill_path / "SKILL.md"
    if not _safe_within(skill_file, skills_dir):
        return web.json_response({"error": "invalid path"}, status=400)
    if not skill_file.exists():
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response({"content": skill_file.read_text(encoding="utf-8", errors="replace")})


async def handle_create_cron(request: web.Request) -> web.json_response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
    jobs_file = HERMES_HOME / "cron" / "jobs.json"
    jobs_data = _read_json(jobs_file)
    if "jobs" not in jobs_data:
        jobs_data["jobs"] = []
    job_id = hashlib.md5(f"{body.get('name','')}{time.time()}".encode()).hexdigest()[:12]
    now = datetime.now(timezone.utc).astimezone().isoformat()
    schedule = body.get("schedule", "0 9 * * *")
    new_job = {
        "id": job_id, "name": body.get("name", "New Job")[:100],
        "prompt": body.get("prompt", "")[:2000],
        "skills": [body["skill"]] if body.get("skill") else [], "skill": body.get("skill", ""),
        "model": None, "provider": None, "base_url": None, "script": None,
        "schedule": {"kind": "cron", "expr": schedule, "display": schedule},
        "schedule_display": schedule,
        "repeat": {"times": None, "completed": 0},
        "enabled": True, "state": "scheduled",
        "paused_at": None, "paused_reason": None,
        "created_at": now, "next_run_at": None,
        "last_run_at": None, "last_status": None,
        "last_error": None, "last_delivery_error": None,
        "deliver": body.get("deliver", "local"), "origin": None,
    }
    jobs_data["jobs"].append(new_job)
    jobs_data["updated_at"] = now
    _write_json(jobs_file, jobs_data)
    return web.json_response({"ok": True, "id": job_id})


async def handle_edit_cron(request: web.Request) -> web.json_response:
    job_id = request.match_info["job_id"]
    if not _SAFE_ID.match(job_id):
        return web.json_response({"ok": False, "error": "invalid job_id"}, status=400)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
    jobs_file = HERMES_HOME / "cron" / "jobs.json"
    jobs_data = _read_json(jobs_file)
    for job in jobs_data.get("jobs", []):
        if job["id"] == job_id:
            for key in ("name", "prompt", "skill", "deliver", "enabled"):
                if key in body:
                    job[key] = body[key]
                    if key == "skill":
                        job["skills"] = [body[key]] if body[key] else []
            if "schedule" in body:
                job["schedule"] = {"kind": "cron", "expr": body["schedule"], "display": body["schedule"]}
                job["schedule_display"] = body["schedule"]
            jobs_data["updated_at"] = datetime.now(timezone.utc).astimezone().isoformat()
            _write_json(jobs_file, jobs_data)
            return web.json_response({"ok": True})
    return web.json_response({"ok": False, "error": "job not found"}, status=404)


async def handle_delete_cron(request: web.Request) -> web.json_response:
    job_id = request.match_info["job_id"]
    if not _SAFE_ID.match(job_id):
        return web.json_response({"ok": False, "error": "invalid job_id"}, status=400)
    jobs_file = HERMES_HOME / "cron" / "jobs.json"
    jobs_data = _read_json(jobs_file)
    jobs_data["jobs"] = [j for j in jobs_data.get("jobs", []) if j["id"] != job_id]
    jobs_data["updated_at"] = datetime.now(timezone.utc).astimezone().isoformat()
    _write_json(jobs_file, jobs_data)
    return web.json_response({"ok": True})


def register_dashboard_routes(app: "web.Application") -> None:
    app.router.add_get("/dashboard", handle_dashboard)
    app.router.add_get("/dashboard/", handle_dashboard)
    app.router.add_get("/api/dashboard/overview", handle_overview)
    app.router.add_get("/api/dashboard/config", handle_get_config)
    app.router.add_post("/api/dashboard/config", handle_set_config)
    app.router.add_get("/api/dashboard/env", handle_get_env)
    app.router.add_post("/api/dashboard/env", handle_set_env)
    app.router.add_get("/api/dashboard/mcp", handle_get_mcp)
    app.router.add_post("/api/dashboard/mcp", handle_set_mcp)
    app.router.add_get("/api/dashboard/soul", handle_get_soul)
    app.router.add_post("/api/dashboard/soul", handle_set_soul)
    app.router.add_get("/api/dashboard/skills", handle_get_skills)
    app.router.add_get("/api/dashboard/logs", handle_get_logs)
    app.router.add_get("/api/dashboard/sessions", handle_get_sessions)
    app.router.add_post("/api/dashboard/restart", handle_restart_gateway)
    app.router.add_get("/api/dashboard/cron/{job_id}/output", handle_get_cron_output)
    app.router.add_post("/api/dashboard/model", handle_set_model)
    app.router.add_get("/api/dashboard/auth", handle_get_auth_status)
    app.router.add_delete("/api/dashboard/sessions/{name}", handle_delete_session)
    app.router.add_post("/api/dashboard/logs/clear", handle_clear_logs)
    app.router.add_get("/api/dashboard/disk", handle_disk_usage)
    app.router.add_get("/api/dashboard/skills/{path:.+}/detail", handle_get_skill_detail)
    app.router.add_post("/api/dashboard/cron/create", handle_create_cron)
    app.router.add_post("/api/dashboard/cron/{job_id}/edit", handle_edit_cron)
    app.router.add_delete("/api/dashboard/cron/{job_id}", handle_delete_cron)
