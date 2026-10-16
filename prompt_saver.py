#!/usr/bin/env python3
"""
Простое приложение: запускается в консоли, поднимает локальный веб-сервер
с формой для ввода промптов и сохраняет их в .py-файл рядом со скриптом.

Логика:
- "Добавить в группу" — кладёт текущий промпт в буфер (для группового сохранения).
- "Сохранить" — сохраняет всё содержимое буфера.
  Если буфер пуст — сохраняет текущие поля как один промпт.
- Поле "Суффикс имени файла" — добавляется к имени файла через "_", если указан.
"""

import http.server
import socketserver
import json
import os
import re
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

  <label for="title">1. Название промпта</label>
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
  async function refreshBuffer() {
    const r = await fetch('/api/buffer');
    const data = await r.json();
    document.getElementById('count').textContent = data.count;
    document.getElementById('bufferPreview').textContent =
      data.count ? JSON.stringify(data.items, null, 2) : '';
  }

  document.getElementById('addBtn').onclick = async () => {
    const title = document.getElementById('title').value.trim();
    const positive = document.getElementById('positive').value;
    const negative = document.getElementById('negative').value;
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
    document.getElementById('title').value = '';
    document.getElementById('positive').value = '';
    document.getElementById('negative').value = '';
    refreshBuffer();
  };

  document.getElementById('saveBtn').onclick = async () => {
    const suffix = document.getElementById('suffix').value.trim();
    const title = document.getElementById('title').value.trim();
    const positive = document.getElementById('positive').value;
    const negative = document.getElementById('negative').value;
    const r = await fetch('/api/save', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({suffix, title, positive, negative})
    });
    const data = await r.json();
    document.getElementById('status').textContent = data.message;
    if (data.saved) {
      document.getElementById('title').value = '';
      document.getElementById('positive').value = '';
      document.getElementById('negative').value = '';
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
    # разрешаем буквы (в т.ч. кириллицу), цифры, дефис, подчёркивание, точку
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
            self._json({"count": len(prompts_buffer), "items": prompts_buffer})
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

            # Если буфер пуст — берём текущие поля как один промпт.
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


def main():
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print("=" * 55)
        print(f"Сервер запущен: http://localhost:{PORT}")
        print(f"Файлы будут сохраняться в: {SCRIPT_DIR}")
        print("Ctrl+C — остановить.")
        print("=" * 55)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nОстановлено.")


if __name__ == "__main__":
    main()