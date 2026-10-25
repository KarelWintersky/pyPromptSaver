#!/usr/bin/env python3
"""
Простое приложение: запускается в консоли, поднимает локальный веб-сервер
с формой для ввода промптов и сохраняет их в .py-файл рядом со скриптом.

Логика:
- "Добавить в группу" — кладёт текущий промпт в буфер (для группового сохранения).
- "Сохранить" — сохраняет всё содержимое буфера.
  Если буфер пуст — сохраняет текущие поля как один промпт.
- Поле "Суффикс имени файла" — добавляется к имени файла через "_", если указан.
- Чекбокс "фиксировать" у поля "Название промпта" — при включении это поле
  не сбрасывается после "Добавить в группу" и "Сохранить".
"""

import http.server
import socketserver
import json
import os
import re
import signal
import sys
from datetime import datetime

PORT = 8000
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Буфер, куда складываются промпты по кнопке "Добавить в группу"
prompts_buffer = []


HTML_PAGE = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Prompt Builder</title>
<style>
  body { font-family: sans-serif; max-width: 800px; margin: 20px auto; padding: 0 15px; background:#1e1e1e; color:#ddd; }
  h1 { color:#7ecfff; }
  label { display:block; margin-top:12px; font-weight:bold; }
  input[type=text], textarea {
    width:100%; padding:8px; margin-top:4px; box-sizing:border-box;
    background:#2b2b2b; color:#eee; border:1px solid #444; border-radius:4px;
  }
  textarea { min-height:100px; resize:vertical; font-family:monospace; }
  .label-row { display:flex; align-items:center; justify-content:space-between; margin-top:12px; }
  .label-row label { margin-top:0; }
  .fix-wrap { display:flex; align-items:center; gap:6px; font-weight:normal; color:#bbb; font-size:13px; user-select:none; cursor:pointer; }
  .fix-wrap input { cursor:pointer; }
  .buttons { margin-top:16px; display:flex; gap:10px; }
  button {
    padding:10px 18px; border:none; border-radius:4px; cursor:pointer;
    font-size:14px; font-weight:bold;
  }
  #addBtn { background:#3a7bd5; color:#fff; }
  #addBtn:hover { background:#2d63ad; }
  #saveBtn { background:#2e9e5b; color:#fff; }
  #saveBtn:hover { background:#247a47; }
  #bufferInfo { margin-top:20px; padding:10px; background:#2b2b2b; border-left:4px solid #3a7bd5; border-radius:4px; }
  #status { margin-top:10px; color:#8f8; min-height:20px; }
  pre { background:#111; padding:8px; border-radius:4px; overflow:auto; }
</style>
</head>
<body>
  <h1>Конструктор промптов</h1>

  <label for="suffix">0. Суффикс имени файла (необязательно)</label>
  <input type="text" id="suffix" placeholder="например: project_x (будет добавлен через _)">

  <div class="label-row">
    <label for="title">1. Название промпта</label>
    <label class="fix-wrap" title="Не сбрасывать это поле после добавления и сохранения">
      <input type="checkbox" id="titleFix"> фиксировать
    </label>
  </div>
  <input type="text" id="title" placeholder="например: portrait_style_01">

  <label for="positive">2. Положительный промпт</label>
  <textarea id="positive" placeholder="masterpiece, best quality, ..."></textarea>

  <label for="negative">3. Негативный промпт</label>
  <textarea id="negative" placeholder="lowres, bad anatomy, ..."></textarea>

  <div class="buttons">
    <button id="addBtn">Добавить в группу</button>
    <button id="saveBtn">Сохранить</button>
  </div>

  <div id="status"></div>
  <div id="bufferInfo">
    В буфере: <span id="count">0</span> промпт(ов).
    Если буфер пуст — «Сохранить» запишет текущие поля как один промпт.
  </div>
  <pre id="bufferPreview"></pre>

<script>
  const titleEl = document.getElementById('title');
  const positiveEl = document.getElementById('positive');
  const negativeEl = document.getElementById('negative');
  const titleFixEl = document.getElementById('titleFix');

  async function refreshBuffer() {
    const r = await fetch('/api/buffer');
    const data = await r.json();
    document.getElementById('count').textContent = data.count;
    const preview = document.getElementById('bufferPreview');
    const label = document.getElementById('bufferPreviewLabel');
    preview.textContent = data.count ? JSON.stringify(data.items, null, 2) : '';
    label.style.display = data.count ? 'block' : 'none';
  }

  function clearFields() {
    if (!titleFixEl.checked) titleEl.value = '';
    positiveEl.value = '';
    negativeEl.value = '';
  }

  document.getElementById('addBtn').onclick = async () => {
    const title = titleEl.value.trim();
    const positive = positiveEl.value;
    const negative = negativeEl.value;
    if (!title && !positive && !negative) {
      document.getElementById('status').textContent = 'Пусто — нечего добавлять.';
      return;
    }
    const r = await fetch('/api/add', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({title, positive, negative})
    });
    const data = await r.json();
    document.getElementById('status').textContent = data.message;
    clearFields();
    refreshBuffer();
  };

  document.getElementById('saveBtn').onclick = async () => {
    const suffix = document.getElementById('suffix').value.trim();
    const title = titleEl.value.trim();
    const positive = positiveEl.value;
    const negative = negativeEl.value;
    const r = await fetch('/api/save', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({suffix, title, positive, negative})
    });
    const data = await r.json();
    document.getElementById('status').textContent = data.message;
    if (data.saved) {
      clearFields();
    }
    refreshBuffer();
  };

  refreshBuffer();
</script>
</body>
</html>
"""


def sanitize_suffix(suffix: str) -> str:
    """Оставляет в суффиксе только безопасные для имени файла символы."""
    if not suffix:
        return ""
    suffix = suffix.strip()
    suffix = re.sub(r"\s+", "_", suffix)
    suffix = re.sub(r"[^\w\-.]+", "", suffix, flags=re.UNICODE)
    suffix = suffix.strip("._-")
    return suffix


def build_filename(suffix: str = "") -> str:
    base = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    safe = sanitize_suffix(suffix)
    if safe:
        return f"{base}_{safe}.py"
    return f"{base}.py"


def build_python_file(items):
    """Формирует содержимое .py-файла в требуемом формате."""
    lines = ["prompts = ["]
    for it in items:
        title = it.get("title", "").replace('"', '\\"')
        positive = it.get("positive", "")
        negative = it.get("negative", "")
        lines.append("    [")
        lines.append('        # title')
        lines.append(f'        "{title}",')
        lines.append('        # positive')
        lines.append('        """')
        lines.append(positive)
        lines.append('        """,')
        lines.append('        # negative')
        lines.append('        """')
        lines.append(negative)
        lines.append('        """')
        lines.append("    ],")
    lines.append("]")
    lines.append("")
    return "\n".join(lines)


class ReusableTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, code, content_type, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, "application/json; charset=utf-8",
                   json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._send(200, "text/html; charset=utf-8", HTML_PAGE.encode("utf-8"))
        elif self.path == "/api/buffer":
            self._json({
                "count": len(prompts_buffer),
                "items": list(reversed(prompts_buffer)),
            })
        else:
            self._send(404, "text/plain; charset=utf-8", b"Not found")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""

        if self.path == "/api/add":
            try:
                data = json.loads(raw.decode("utf-8"))
            except Exception:
                return self._json({"message": "Ошибка: некорректный JSON"}, 400)
            prompts_buffer.append({
                "title": data.get("title", ""),
                "positive": data.get("positive", ""),
                "negative": data.get("negative", ""),
            })
            return self._json({"message": f"Добавлено в группу. В буфере: {len(prompts_buffer)}"})

        if self.path == "/api/save":
            try:
                data = json.loads(raw.decode("utf-8")) if raw else {}
            except Exception:
                data = {}

            suffix = data.get("suffix", "")

            if prompts_buffer:
                items = list(prompts_buffer)
            else:
                title = (data.get("title", "") or "").strip()
                positive = data.get("positive", "")
                negative = data.get("negative", "")
                if not title and not positive and not negative:
                    return self._json({
                        "message": "Нечего сохранять: буфер пуст и поля пусты.",
                        "saved": False,
                    }, 400)
                items = [{"title": title, "positive": positive, "negative": negative}]

            filename = build_filename(suffix)
            path = os.path.join(SCRIPT_DIR, filename)
            with open(path, "w", encoding="utf-8") as f:
                f.write(build_python_file(items))

            count = len(items)
            prompts_buffer.clear()
            return self._json({
                "message": f"Сохранено {count} промпт(ов) в {filename}. Буфер очищен.",
                "saved": True,
            })

        self._send(404, "text/plain; charset=utf-8", b"Not found")

    def log_message(self, fmt, *args):
        pass


def _force_exit(signum, frame):
    """Жёсткий выход по Ctrl+C / SIGTERM — без ожидания второго сигнала."""
    print("\nОстановлено.", flush=True)
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(0)


def main():
    signal.signal(signal.SIGINT, _force_exit)
    signal.signal(signal.SIGTERM, _force_exit)

    try:
        httpd = ReusableTCPServer(("", PORT), Handler)
    except OSError as e:
        print(f"Не удалось занять порт {PORT}: {e}")
        print(f"Проверь, не занят ли порт: lsof -i :{PORT}")
        return

    print("=" * 55)
    print(f"Сервер запущен: http://localhost:{PORT}")
    print(f"Файлы будут сохраняться в: {SCRIPT_DIR}")
    print("Ctrl+C — остановить.")
    print("=" * 55)
    sys.stdout.flush()

    try:
        httpd.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        _force_exit(signal.SIGINT, None)
    finally:
        try:
            httpd.server_close()
        except Exception:
            pass


if __name__ == "__main__":
    main()

