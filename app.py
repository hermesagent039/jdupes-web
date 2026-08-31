#!/usr/bin/env python3
"""Manual web wrapper for recursive jdupes scans."""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


SUMMARY_RE = re.compile(r"(?P<files>\d+) duplicate files? \(in (?P<sets>\d+) sets?\)")


class AppState:
    def __init__(self, root: str, jdupes_bin: str = "jdupes") -> None:
        self.root = os.path.realpath(root)
        self.jdupes_bin = jdupes_bin
        self.lock = threading.Lock()
        self.job: dict[str, Any] = self._idle()
        self.process: subprocess.Popen[str] | None = None

    @staticmethod
    def _idle() -> dict[str, Any]:
        return {
            "status": "idle", "mode": None, "total_files": 0, "processed_files": 0,
            "duplicate_files": 0, "duplicate_sets": 0, "deleted_files": 0,
            "message": "Готово к запуску", "error": None,
        }

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            result = dict(self.job)
            result["progress"] = round(result["processed_files"] * 100 / result["total_files"], 1) if result["total_files"] else 0
            return result

    def start(self, mode: str, confirmed: bool = False) -> bool:
        if mode not in {"search", "delete"} or (mode == "delete" and not confirmed):
            return False
        with self.lock:
            if self.job["status"] in {"counting", "running", "stopping"}:
                return False
            self.job = {**self._idle(), "status": "counting", "mode": mode, "message": "Подсчитываем файлы…"}
        threading.Thread(target=self._run, args=(mode,), daemon=True).start()
        return True

    def stop(self) -> bool:
        with self.lock:
            if self.job["status"] not in {"counting", "running"}:
                return False
            self.job["status"] = "stopping"
            self.job["message"] = "Останавливаем…"
            proc = self.process
        if proc and proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
        return True

    def _set(self, **values: Any) -> None:
        with self.lock:
            self.job.update(values)

    def _files(self) -> set[str]:
        return {str(path) for path in Path(self.root).rglob("*") if path.is_file()}

    def _run_jdupes(self, args: list[str]) -> tuple[int, str, str]:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        with self.lock:
            self.process = proc
        stdout, stderr = proc.communicate()
        with self.lock:
            self.process = None
        return proc.returncode, stdout or "", stderr or ""

    def _run(self, mode: str) -> None:
        try:
            total = len(self._files())
            self._set(total_files=total, status="running", message="Сканируем дерево файлов…")
            if total == 0:
                self._set(status="completed", message="В папке нет файлов", processed_files=0)
                return

            base = [self.jdupes_bin, "-r"]
            summary_code, summary_out, summary_err = self._run_jdupes(base + ["-m", self.root])
            match = SUMMARY_RE.search(summary_out)
            duplicate_files = int(match.group("files")) if match else 0
            duplicate_sets = int(match.group("sets")) if match else 0
            self._set(duplicate_files=duplicate_files, duplicate_sets=duplicate_sets)
            with self.lock:
                stopping = self.job["status"] == "stopping"
            if stopping:
                self._set(status="stopped", message="Остановлено", processed_files=0)
                return
            if summary_code != 0:
                error = (summary_err or summary_out or "jdupes завершился с ошибкой").strip()[-1000:]
                self._set(status="error", message="Не удалось выполнить поиск", error=error)
                return

            if mode == "search":
                self._set(status="completed", message="Поиск завершён", processed_files=total)
                return

            self._set(message="Удаляем найденные дубликаты…")
            before = self._files()
            delete_code, delete_out, delete_err = self._run_jdupes(base + ["-d", "-N", self.root])
            deleted = len(before - self._files())
            with self.lock:
                stopping = self.job["status"] == "stopping"
            self._set(deleted_files=deleted, processed_files=total)
            if stopping:
                self._set(status="stopped", message="Остановлено")
            elif delete_code == 0:
                self._set(status="completed", message="Удаление завершено")
            else:
                error = (delete_err or delete_out or "Не удалось удалить все дубликаты").strip()[-1000:]
                self._set(status="error", message="Удаление завершено с ошибкой", error=error)
        except Exception as exc:
            self._set(status="error", message="Ошибка выполнения", error=str(exc)[-1000:])
        finally:
            with self.lock:
                self.process = None


PAGE = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>jdupes — очистка файлов</title>
<style>
:root{--ink:#172033;--muted:#667085;--line:#e5e9f0;--paper:#fff;--canvas:#f6f8fb;--blue:#2864dc;--blue-dark:#1f4fb1;--green:#16845b;--green-soft:#e9f7f0;--amber:#9a6700;--amber-soft:#fff7df;--red:#c0393b;--shadow:0 18px 50px rgba(31,48,82,.09)}
*{box-sizing:border-box}body{margin:0;background:var(--canvas);color:var(--ink);font:15px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}button,select{font:inherit}.shell{width:min(1080px,calc(100% - 40px));margin:0 auto;padding:34px 0 56px}.topbar{display:flex;align-items:center;justify-content:space-between;margin-bottom:30px}.brand{display:flex;align-items:center;gap:13px}.brand-mark{width:38px;height:38px;border-radius:11px;background:var(--blue);color:white;display:grid;place-items:center;font-weight:800;font-size:18px;box-shadow:0 8px 18px rgba(40,100,220,.24)}.brand-name{font-size:20px;font-weight:800;letter-spacing:-.03em}.brand-sub{color:var(--muted);font-size:13px;margin-top:1px}.root-pill{border:1px solid var(--line);background:var(--paper);border-radius:999px;padding:8px 14px;color:var(--muted);font-size:13px}.hero{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(280px,.75fr);gap:28px;align-items:end;margin-bottom:26px}.eyebrow{color:var(--blue);font-weight:750;text-transform:uppercase;letter-spacing:.1em;font-size:11px;margin:0 0 10px}.hero h1{font-size:clamp(30px,4vw,48px);line-height:1.04;letter-spacing:-.055em;margin:0 0 12px}.hero p{color:var(--muted);font-size:16px;max-width:570px;margin:0}.info-note{background:var(--paper);border:1px solid var(--line);border-radius:16px;padding:18px 20px;box-shadow:0 8px 24px rgba(31,48,82,.04)}.info-note strong{display:block;margin-bottom:4px}.info-note span{color:var(--muted);font-size:13px}.panel{background:var(--paper);border:1px solid var(--line);border-radius:20px;box-shadow:var(--shadow);padding:26px}.panel-head{display:flex;justify-content:space-between;gap:20px;align-items:flex-start;margin-bottom:24px}.panel-title{font-size:18px;font-weight:780;margin:0 0 4px}.panel-copy{color:var(--muted);font-size:13px;margin:0}.mode-label{display:block;font-size:12px;font-weight:750;color:var(--muted);margin-bottom:8px}.mode-select{width:230px;height:46px;border:1px solid #cdd5e1;border-radius:11px;background:#fff;padding:0 13px;color:var(--ink);font-weight:650;outline:none}.mode-select:focus{border-color:var(--blue);box-shadow:0 0 0 3px rgba(40,100,220,.13)}.warning{display:none;margin:0 0 20px;padding:12px 14px;border-radius:11px;background:var(--amber-soft);color:var(--amber);font-size:13px}.warning.show{display:flex;gap:9px;align-items:flex-start}.actions{display:flex;gap:10px;margin-bottom:26px}.btn{border:0;border-radius:11px;height:46px;padding:0 19px;font-weight:750;cursor:pointer;transition:.18s ease}.btn-primary{background:var(--blue);color:#fff;box-shadow:0 7px 14px rgba(40,100,220,.19)}.btn-primary:hover{background:var(--blue-dark);transform:translateY(-1px)}.btn-secondary{background:#eef1f5;color:#475467}.btn-secondary:hover{background:#e3e8ef}.btn:disabled{opacity:.5;cursor:not-allowed;transform:none;box-shadow:none}.progress-block{border-top:1px solid var(--line);padding-top:22px}.status-row{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}.status{display:flex;align-items:center;gap:9px;font-weight:700}.dot{width:9px;height:9px;border-radius:50%;background:#aab3c0}.dot.busy{background:var(--blue);box-shadow:0 0 0 4px rgba(40,100,220,.12)}.dot.done{background:var(--green)}.dot.error{background:var(--red)}.percent{font-weight:800;color:var(--blue)}.track{height:10px;background:#edf0f4;border-radius:99px;overflow:hidden}.fill{height:100%;width:0;background:var(--blue);border-radius:inherit;transition:width .35s ease}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:22px}.stat{background:#f8fafc;border:1px solid #edf0f4;border-radius:13px;padding:14px 15px;min-width:0}.stat b{display:block;font-size:25px;line-height:1.1;letter-spacing:-.04em;margin-bottom:5px}.stat span{display:block;color:var(--muted);font-size:12px}.result{display:none;margin-top:18px;border-radius:14px;padding:17px 18px;border:1px solid #ccebdc;background:var(--green-soft)}.result.show{display:flex;justify-content:space-between;align-items:center;gap:16px}.result.error-state{background:#fff0f0;border-color:#f2cccc}.result-main{font-weight:750}.result-detail{color:#527064;font-size:13px;margin-top:3px}.result.error-state .result-detail{color:#8d5555}.error{color:var(--red);white-space:pre-wrap;font-size:13px;margin-top:14px}.footer{color:#98a2b3;text-align:center;font-size:12px;margin-top:20px}@media(max-width:760px){.shell{width:min(100% - 24px,600px);padding-top:22px}.topbar{margin-bottom:24px}.root-pill{display:none}.hero{grid-template-columns:1fr;gap:16px;margin-bottom:18px}.hero h1{font-size:35px}.info-note{padding:14px 16px}.panel{padding:19px 16px;border-radius:16px}.panel-head{display:block;margin-bottom:20px}.mode-select{width:100%;margin-top:17px}.actions{margin-top:20px;margin-bottom:22px}.btn{flex:1;padding:0 10px}.stats{grid-template-columns:repeat(2,1fr);gap:9px}.stat{padding:12px}.stat b{font-size:22px}.result.show{display:block}.result .btn{width:100%;margin-top:12px}}
</style></head><body><main class="shell">
<header class="topbar"><div class="brand"><div class="brand-mark">j</div><div><div class="brand-name">jdupes</div><div class="brand-sub">умная очистка дубликатов</div></div></div><div class="root-pill">Сканирование: /data/scan</div></header>
<section class="hero"><div><p class="eyebrow">Контроль файлов</p><h1>Найдите лишнее.<br>Оставьте важное.</h1><p>Рекурсивно проверяйте папку на дубликаты и удаляйте лишние копии только после явного подтверждения.</p></div><div class="info-note"><strong>Безопасный ручной запуск</strong><span>Ничего не происходит автоматически. Во время работы можно остановить операцию.</span></div></section>
<section class="panel"><div class="panel-head"><div><h2 class="panel-title">Новая операция</h2><p class="panel-copy">Выберите действие для дерева файлов</p></div><div><label class="mode-label" for="mode">Режим операции</label><select class="mode-select" id="mode"><option value="search">Поиск дубликатов</option><option value="delete">Удаление дубликатов</option></select></div></div>
<div id="warn" class="warning"><span>⚠</span><span><strong>Удаление необратимо.</strong><br>Будет сохранена первая копия каждого набора, остальные файлы будут удалены.</span></div>
<div class="actions"><button class="btn btn-primary" id="start">Запустить операцию</button><button class="btn btn-secondary" id="stop" disabled>Остановить</button></div>
<div class="progress-block"><div class="status-row"><div class="status"><span class="dot" id="dot"></span><span id="status">Готово к запуску</span></div><span class="percent" id="percent">0%</span></div><div class="track"><div class="fill" id="fill"></div></div><div class="stats"><div class="stat"><b id="total">0</b><span>всего файлов</span></div><div class="stat"><b id="processed">0</b><span>обработано</span></div><div class="stat"><b id="dupes">0</b><span>дубликатов найдено</span></div><div class="stat"><b id="sets">0</b><span>наборов дубликатов</span></div></div></div>
<div id="result" class="result"><div><div class="result-main" id="result-main"></div><div class="result-detail" id="result-detail"></div></div></div><div id="error" class="error"></div></section><div class="footer">Данные не покидают ваш сервер · корень сканирования фиксирован: /data/scan</div></main>
<script>
const $=id=>document.getElementById(id), mode=$('mode'), warn=$('warn'), start=$('start'), stop=$('stop');
mode.onchange=()=>warn.classList.toggle('show',mode.value==='delete');
start.onclick=async()=>{let confirmed=mode.value==='delete'&&window.confirm('Удалить найденные дубликаты без возможности восстановления?');if(mode.value==='delete'&&!confirmed)return;const r=await fetch('/api/start',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({mode:mode.value,confirmed})});if(!r.ok){const x=await r.json();window.alert(x.error||'Ошибка запуска')}};
stop.onclick=()=>fetch('/api/stop',{method:'POST'});
function render(s){const busy=['counting','running','stopping'].includes(s.status);$('fill').style.width=s.progress+'%';$('percent').textContent=s.progress+'%';$('status').textContent=s.message||s.status;$('total').textContent=s.total_files.toLocaleString('ru-RU');$('processed').textContent=s.processed_files.toLocaleString('ru-RU');$('dupes').textContent=s.duplicate_files.toLocaleString('ru-RU');$('sets').textContent=s.duplicate_sets.toLocaleString('ru-RU');start.disabled=busy;stop.disabled=!busy;$('dot').className='dot '+(busy?'busy':s.status==='error'?'error':s.status==='completed'?'done':'');$('error').textContent=s.error||'';const result=$('result');if(s.status==='completed'){result.classList.add('show');result.classList.remove('error-state');$('result-main').textContent=s.mode==='delete'?`Удалено дубликатов: ${s.deleted_files.toLocaleString('ru-RU')}`:`Найдено дубликатов: ${s.duplicate_files.toLocaleString('ru-RU')}`;$('result-detail').textContent=s.mode==='delete'?`Освобождены лишние копии в ${s.duplicate_sets.toLocaleString('ru-RU')} наборах.`:`Дубликаты объединены в ${s.duplicate_sets.toLocaleString('ru-RU')} наборов.`}else if(s.status==='error'){result.classList.add('show','error-state');$('result-main').textContent='Операция завершилась с ошибкой';$('result-detail').textContent='Проверьте права доступа к папке и попробуйте снова.'}else result.classList.remove('show')}
async function poll(){try{render(await (await fetch('/api/status',{cache:'no-store'})).json())}finally{setTimeout(poll,800)}}poll();
</script></body></html>"""


def create_server(host: str, port: int, state: AppState) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def _json(self, status: int, payload: dict[str, Any]) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

        def do_GET(self) -> None:
            if self.path == "/":
                data = PAGE.encode(); self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
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
