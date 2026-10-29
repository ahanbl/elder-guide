"""适老化「引导标注」Demo —— 零依赖（只用 Python 标准库 + Pillow）。

用法：
    python app.py
浏览器打开 http://127.0.0.1:8765

三件事：
 1. 接收一张手机截图；
 2. 告诉你/模型「这一步该点哪里」；
 3. 生成「整屏压暗 + 目标挖亮 + 箭头 + 大字」引导图。

AI 来源二选一：
 - 有 dify.json（{base_url, token}）→ 走 Dify 工作流；
 - 否则 → 直接调本机 Ollama。
/api/steps 给 Dify 的 HTTP 节点用，返回 text/plain 以避免中文乱码。
"""
from __future__ import annotations

import base64
import io
import json
import pathlib
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_PATH = "C:/Windows/Fonts/msyh.ttc"
BOLD_PATH = "C:/Windows/Fonts/msyhbd.ttc"
OLLAMA = "http://127.0.0.1:11434/api/generate"
DIFY_CONFIG = pathlib.Path(__file__).with_name("dify.json")


def _font(size: int, bold: bool = False):
    try:
        return ImageFont.truetype(BOLD_PATH if bold else FONT_PATH, size)
    except OSError:
        return ImageFont.load_default()


def _fit_font(draw, text: str, max_w: int, size: int, bold: bool = False, min_size: int = 20):
    while size > min_size:
        font = _font(size, bold)
        if draw.textlength(text, font=font) <= max_w:
            return font
        size -= 2
    return _font(min_size, bold)


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    lines, cur = [], ""
    for ch in text:
        trial = cur + ch
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def annotate(src: bytes, x: int, y: int, title: str, step: str, radius: int = 120) -> bytes:
    """在截图上画引导层：压暗整屏、挖亮目标圆、箭头 + 说明卡。"""
    base = Image.open(io.BytesIO(src)).convert("RGB")
    w, h = base.size
    scale = max(w, h) / 750.0
    r = max(60, int(radius * scale))
    r = min(r, int(min(w, h) * 0.42))

    shade = Image.new("RGBA", (w, h), (0, 0, 0, 180))
    out = Image.alpha_composite(base.convert("RGBA"), shade).convert("RGB")

    box = (max(0, x - r), max(0, y - r), min(w, x + r), min(h, y + r))
    crop = base.crop(box)
    mask = Image.new("L", crop.size, 0)
    ImageDraw.Draw(mask).ellipse([0, 0, crop.size[0], crop.size[1]], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(r * 0.06))
    out.paste(crop, box[:2], mask)

    d = ImageDraw.Draw(out)
    for width, color in ((max(4, int(9 * scale)), (255, 214, 0)), (max(2, int(4 * scale)), (255, 255, 255))):
        d.ellipse([x - r, y - r, x + r, y + r], outline=color, width=width)

    ay = max(int(40 * scale), y - int(r * 2.2))
    d.line([x, ay, x, y - r - int(8 * scale)], fill=(255, 214, 0), width=max(6, int(12 * scale)))
    tri = int(22 * scale)
    d.polygon([(x - tri, y - r - int(28 * scale)), (x + tri, y - r - int(28 * scale)), (x, y - r)], fill=(255, 214, 0))

    pad = int(26 * scale)
    left, right = int(44 * scale), w - int(44 * scale)
    max_w = right - left - pad * 2

    fs_title = max(22, int(30 * scale))
    font_title = _font(fs_title)
    fs_step = max(26, int(46 * scale))
    font_step = _fit_font(d, step or "点一下高亮的位置", max_w, fs_step, bold=True)
    step_fs = font_step.size
    lines = _wrap(d, step or "点一下高亮的位置", font_step, max_w)[:3]
    line_h = int(step_fs * 1.32)
    gap = int(12 * scale)

    card_h = pad * 2 + fs_title + gap + len(lines) * line_h
    card_top = max(int(24 * scale), ay - card_h - int(28 * scale))
    d.rounded_rectangle([left, card_top, right, card_top + card_h], radius=int(22 * scale), fill=(255, 255, 255))
    d.text((left + pad, card_top + pad), title or "照着亮的地方点", font=font_title, fill="#07C160")
    ty = card_top + pad + fs_title + gap
    for line in lines:
        d.text((left + pad, ty), line, font=font_step, fill="#111111")
        ty += line_h

    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


def ask_ollama(question: str, screen: str = "微信首页") -> str:
    prompt = (
        "你是一位极其耐心的年轻人，负责教 70 岁的长辈用手机。\n"
        f"长辈现在停在「{screen}」这个页面，他的问题是：{question}\n"
        "请给出 3 步以内的操作，每步不超过 15 个字，用大白话，不要任何术语，不要解释原理。\n"
        "现在请直接输出步骤，每行一步，不要编号。"
    )
    body = json.dumps({"model": "qwen2.5:7b", "prompt": prompt, "stream": False}).encode()
    req = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode()).get("response", "").strip()
    except (urllib.error.URLError, TimeoutError) as exc:
        return f"（本地模型没连上：{exc}）"


def _load_dify():
    try:
        return json.loads(DIFY_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def ask_dify(question: str, cfg: dict) -> str:
    body = json.dumps(
        {"inputs": {"query": question}, "response_mode": "blocking", "user": "elder-guide-demo"}
    ).encode()
    req = urllib.request.Request(
        cfg["base_url"].rstrip("/") + "/v1/workflows/run",
        data=body,
        headers={"Authorization": f"Bearer {cfg['token']}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode())
        outputs = (data.get("data") or {}).get("outputs", {})
        raw = outputs.get("steps_raw", "")
        if isinstance(raw, str) and raw.strip().startswith("{"):
            raw = json.loads(raw).get("response", raw)
        return str(raw).strip()
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return f"（Dify 没连上：{exc}）"


def ask(question: str) -> tuple[str, str]:
    cfg = _load_dify()
    if cfg and cfg.get("token"):
        return ask_dify(question, cfg), "Dify"
    return ask_ollama(question), "本地 Ollama"


PAGE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>适老化引导图生成器</title>
<style>
*{box-sizing:border-box} body{margin:0;font-family:"Microsoft YaHei",system-ui;background:#f4f6f8;color:#111}
.wrap{max-width:1180px;margin:0 auto;padding:24px}
h1{font-size:26px;margin:0 0 6px} .sub{color:#666;margin-bottom:20px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}
.panel{background:#fff;border-radius:14px;padding:16px;box-shadow:0 2px 10px rgba(0,0,0,.06)}
canvas{width:100%;border-radius:10px;cursor:crosshair;background:#eaeaea;max-height:520px;object-fit:contain}
.row{display:flex;gap:10px;margin-top:12px;flex-wrap:wrap}
input[type=text]{flex:1;min-width:200px;padding:10px 12px;border:1px solid #ddd;border-radius:10px;font-size:15px}
button{padding:10px 18px;border:0;border-radius:10px;background:#07C160;color:#fff;font-size:15px;cursor:pointer}
button.ghost{background:#eef1f4;color:#333}
.hint{font-size:13px;color:#888;margin-top:10px}
img.out{width:100%;border-radius:10px}
</style></head><body><div class="wrap">
<h1>适老化引导图生成器 <span style="font-size:14px;color:#999">v0.2</span></h1>
<div class="sub">上传一张家人手机的截图 → 点一下「该点哪里」→ 生成引导图</div>
<div class="grid">
  <div class="panel">
    <input type="file" id="file" accept="image/*"><div class="hint">或者直接用下面的示例图点一点</div>
    <canvas id="cv"></canvas>
    <div class="row">
      <input type="text" id="q" placeholder="家人的问题，例如：我不会发朋友圈">
      <button class="ghost" onclick="askAI()">让 AI 写步骤</button>
    </div>
    <div class="row">
      <input type="text" id="title" value="第 1 步" placeholder="标题">
      <input type="text" id="step" placeholder="这一步让他点什么">
      <button onclick="render()">生成引导图</button>
    </div>
    <div class="hint" id="status"></div>
  </div>
  <div class="panel">
    <div id="outbox" class="hint">生成的引导图会出现在这里</div>
  </div>
</div></div>
<script>
let img=new Image(), pt=null, cv=document.getElementById('cv'), ctx=cv.getContext('2d');
function draw(){
  if(!img.src) return;
  cv.width=img.naturalWidth; cv.height=img.naturalHeight;
  ctx.drawImage(img,0,0);
  if(pt){ ctx.strokeStyle='#ffd600'; ctx.lineWidth=Math.max(4,cv.width/160); ctx.beginPath();
    ctx.arc(pt.x,pt.y,cv.width/7,0,Math.PI*2); ctx.stroke(); }
}
cv.addEventListener('click',e=>{
  const r=cv.getBoundingClientRect();
  pt={x:Math.round((e.clientX-r.left)*cv.width/r.width), y:Math.round((e.clientY-r.top)*cv.height/r.height)};
  draw();
});
function loadSrc(src){ img.onload=()=>{pt=null;draw();}; img.src=src; }
document.getElementById('file').addEventListener('change',e=>{
  const f=e.target.files[0]; if(!f) return; const fr=new FileReader(); fr.onload=()=>loadSrc(fr.result); fr.readAsDataURL(f);
});
loadSrc('/sample.png');
async function askAI(){
  const q=document.getElementById('q').value.trim(); if(!q) return;
  document.getElementById('status').textContent='模型思考中…';
  const r=await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({q})});
  const j=await r.json();
  document.getElementById('step').value=(j.answer||'').split('\\n').filter(s=>s.trim()).join(' → ');
  document.getElementById('status').textContent='步骤来自：'+(j.source||'?');
}
async function render(){
  if(!pt){ document.getElementById('status').textContent='先在上面的图上点一下要点的位置'; return; }
  document.getElementById('status').textContent='生成中…';
  const payload={image:img.src, x:pt.x, y:pt.y,
      title:document.getElementById('title').value, step:document.getElementById('step').value};
  const r=await fetch('/api/annotate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const j=await r.json();
  if(j.error){ document.getElementById('status').textContent=j.error; return; }
  document.getElementById('outbox').innerHTML='<img class="out" src="'+j.png+'"><div class="hint"><a download="引导图.png" href="'+j.png+'">下载引导图</a></div>';
  document.getElementById('status').textContent='完成 ✅';
}
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._send(200, PAGE.encode("utf-8"))
        if self.path == "/sample.png":
            try:
                with open(pathlib.Path(__file__).with_name("sample.png"), "rb") as fh:
                    return self._send(200, fh.read(), "image/png")
            except OSError:
                return self._send(404, b"no sample")
        return self._send(404, b"not found")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, b'{"error":"bad json"}', "application/json")

        if self.path == "/api/ask":
            text, source = ask(payload.get("q", ""))
            body = json.dumps({"answer": text, "source": source}, ensure_ascii=False).encode("utf-8")
            return self._send(200, body, "application/json; charset=utf-8")

        # 给 Dify 的 HTTP 节点用：纯文本 + 明确 charset，避免中文乱码
        if self.path == "/api/steps":
            text = ask_ollama(payload.get("query", ""))
            return self._send(200, text.encode("utf-8"), "text/plain; charset=utf-8")

        if self.path == "/api/annotate":
            data = payload.get("image", "")
            if "," in data:
                data = data.split(",", 1)[1]
            try:
                png = annotate(
                    base64.b64decode(data),
                    int(payload.get("x", 0)),
                    int(payload.get("y", 0)),
                    str(payload.get("title", "")),
                    str(payload.get("step", "")),
                )
            except Exception as exc:  # noqa: BLE001
                body = json.dumps({"error": f"标注失败：{exc}"}, ensure_ascii=False).encode("utf-8")
                return self._send(200, body, "application/json; charset=utf-8")
            b64 = "data:image/png;base64," + base64.b64encode(png).decode()
            return self._send(200, json.dumps({"png": b64}).encode(), "application/json")

        return self._send(404, b"not found")


if __name__ == "__main__":
    print("引导图生成器: http://127.0.0.1:8765")
    ThreadingHTTPServer(("0.0.0.0", 8765), Handler).serve_forever()
