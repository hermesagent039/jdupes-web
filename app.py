#!/usr/bin/env python3
"""Small manual web wrapper for recursive jdupes scans."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


class AppState:
    def __init__(self, root: str, jdupes_bin: str = "jdupes") -> None:
        self.root = os.path.realpath(root)
        self.jdupes_bin = jdupes_bin
        self.lock = threading.Lock()
        self.job: dict[str, Any] = self._idle()
        self.process: subprocess.Popen[str] | None = None

    @staticmethod
    def _idle() -> dict[str, Any]:
        return {"status": "idle", "mode": None, "total_files": 0,
                "processed_files": 0, "message": "Готово к запуску", "error": None}

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            result = dict(self.job)
            result["progress"] = (round(result["processed_files"] * 100 / result["total_files"], 1)
                                   if result["total_files"] else 0)
            return result

    def start(self, mode: str, confirmed: bool = False) -> bool:
        if mode not in {"search", "delete"} or (mode == "delete" and not confirmed):
            return False
        with self.lock:
            if self.job["status"] in {"counting", "running", "stopping"}:
                return False
            self.job = {"status": "counting", "mode": mode, "total_files": 0,
                        "processed_files": 0, "message": "Подсчёт файлов…", "error": None}
        threading.Thread(target=self._run, args=(mode,), daemon=True).start()
        return True

    def stop(self) -> bool:
        with self.lock:
            if self.job["status"] not in {"counting", "running"}:
                return False
            self.job["status"] = "stopping"
            self.job["message"] = "Остановка…"
            proc = self.process
        if proc and proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
        return True

    def _set(self, **values: Any) -> None:
        with self.lock:
            self.job.update(values)

    def _run(self, mode: str) -> None:
        try:
            total = sum(1 for path in Path(self.root).rglob("*") if path.is_file())
            self._set(total_files=total, status="running", message="Выполняется…")
            if total == 0:
                self._set(status="completed", message="Файлы не найдены", processed_files=0)
                return
            # The UI confirmation is the safety gate; -N prevents jdupes from
            # opening an interactive prompt in the detached worker.
            args = [self.jdupes_bin, "-r"]
            if mode == "delete":
                args.append("-N")
            args.append(self.root)
            with subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                  text=True, start_new_session=True) as proc:
                with self.lock:
                    self.process = proc
                _, stderr = proc.communicate()
                with self.lock:
                    self.process = None
                    stopping = self.job["status"] == "stopping"
                if stopping:
                    self._set(status="stopped", message="Остановлено", processed_files=0)
                elif proc.returncode == 0:
                    self._set(status="completed", message="Завершено", processed_files=total)
                else:
                    error = (stderr or "jdupes завершился с ошибкой").strip()[-1000:]
                    self._set(status="error", message="Ошибка выполнения", error=error)
        except Exception as exc:
            self._set(status="error", message="Ошибка", error=str(exc)[-1000:])
        finally:
            with self.lock:
                self.process = None


PAGE = """<!doctype html><html lang='ru'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'><title>jdupes</title>
<style>body{font:16px system-ui;max-width:680px;margin:40px auto;padding:0 16px;color:#222}h1{font-size:28px}.card{border:1px solid #ddd;border-radius:10px;padding:20px}label{display:block;margin:12px 0 6px}select,button{font:inherit;padding:10px 14px;border-radius:7px;border:1px solid #aaa}button{background:#1769e0;color:white;border:0;cursor:pointer}button:disabled{opacity:.5;cursor:wait}#stop{background:#777;margin-left:8px}.bar{height:20px;background:#eee;border-radius:10px;overflow:hidden;margin:20px 0 10px}.fill{height:100%;background:#2e9b55;width:0;transition:width .3s}.stats{display:flex;gap:24px}.stat b{display:block;font-size:25px}.warn{color:#a33;display:none;margin:12px 0}.error{color:#a00;white-space:pre-wrap}</style></head>
<body><h1>jdupes</h1><div class='card'><label for='mode'>Режим</label><select id='mode'><option value='search'>Поиск дублей</option><option value='delete'>Удаление дублей</option></select><div id='warn' class='warn'>Удаление файлов необратимо. Для запуска требуется подтверждение.</div><div><button id='start'>Запустить</button><button id='stop' disabled>Остановить</button></div><div class='bar'><div id='fill' class='fill'></div></div><div id='status'>Готово к запуску</div><div class='stats'><div class='stat'><b id='total'>0</b>всего файлов</div><div class='stat'><b id='processed'>0</b>обработано</div></div><div id='error' class='error'></div></div>
<script>const mode=document.querySelector('#mode'),warn=document.querySelector('#warn'),start=document.querySelector('#start'),stop=document.querySelector('#stop');mode.onchange=()=>warn.style.display=mode.value==='delete'?'block':'none';start.onclick=async()=>{let confirmed=mode.value==='delete'&&confirm('Удалить найденные дубликаты?');if(mode.value==='delete'&&!confirmed)return;let r=await fetch('/api/start',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({mode:mode.value,confirmed})});if(!r.ok)alert((await r.json()).error||'Ошибка запуска');};stop.onclick=()=>fetch('/api/stop',{method:'POST'});async function poll(){let s=await (await fetch('/api/status')).json();document.querySelector('#fill').style.width=s.progress+'%';document.querySelector('#status').textContent=s.message||s.status;document.querySelector('#total').textContent=s.total_files;document.querySelector('#processed').textContent=s.processed_files;document.querySelector('#error').textContent=s.error||'';let busy=['counting','running','stopping'].includes(s.status);start.disabled=busy;stop.disabled=!busy;setTimeout(poll,1000)}poll();</script></body></html>"""


def create_server(host: str, port: int, state: AppState) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def _json(self, status: int, payload: dict[str, Any]) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

        def do_GET(self) -> None:
            if self.path == "/":
                data = PAGE.encode(); self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
            elif self.path == "/healthz": self._json(200, {"status": "ok"})
            elif self.path == "/api/status": self._json(200, state.snapshot())
            else: self._json(404, {"error": "not found"})

        def do_POST(self) -> None:
            if self.path == "/api/stop":
                self._json(202 if state.stop() else 409, {"status": state.snapshot()["status"]}); return
            if self.path != "/api/start": self._json(404, {"error": "not found"}); return
            try:
                length = int(self.headers.get("Content-Length", "0")); body = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, json.JSONDecodeError): self._json(400, {"error": "invalid JSON"}); return
            mode, confirmed = body.get("mode"), bool(body.get("confirmed"))
            if mode == "delete" and not confirmed: self._json(400, {"error": "confirmation is required for delete mode"}); return
            if not state.start(mode, confirmed): self._json(409, {"error": "job is already running or mode is invalid"}); return
            self._json(202, {"status": "started", "mode": mode})

        def log_message(self, *_: Any) -> None: return
    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    state = AppState(os.environ.get("SCAN_ROOT", "/data/scan"), os.environ.get("JDUPES_BIN", "jdupes"))
    server = create_server(os.environ.get("WEB_HOST", "0.0.0.0"), int(os.environ.get("WEB_PORT", "8080")), state)
    server.serve_forever()


if __name__ == "__main__": main()
