r"""PPT / OnlyOffice 卡片渲染轨道（v3.8，R08）。

两条路：
1. 自动生成：用 python-pptx 把分镜要点做成标准 .pptx（深色信息卡片），再用无头 Chromium 把每页渲染成 PNG，
   交给 video_maker 当某一镜的画面（Ken Burns 推拉）。
2. 导入精修：作者用本机 OnlyOffice 改好的 .pptx 放到项目里，填进 settings.ppt_file；能找 LibreOffice/soffice 时
   转成 PDF + 图片序列；找不到就明确降级为自动卡片，不阻塞成片。

PPT 卡片只负责“知识科普算账/对比”这类信息页；搞笑反转仍可用网页动效 + Q 版 GIF。
"""
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class RenderPptError(RuntimeError):
    pass


def _esc(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


def _points(shot):
    raw = shot.get("ppt_points")
    if isinstance(raw, list) and raw:
        return [str(x).strip() for x in raw if str(x).strip()][:5]
    text = str(shot.get("text") or "")
    parts = [x.strip(" ，,。；;：:！!？?") for x in re.split(r"[。；;！!？?\n]+", text) if x.strip()]
    return (parts or [text])[:4]


def auto_pptx(project_dir, project) -> Path:
    """生成标准 .pptx 信息卡片（9:16 或 16:9）。没装 python-pptx 就跳过。"""
    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt
        from pptx.dml.color import RGBColor
        from pptx.enum.text import PP_ALIGN
    except ImportError:
        raise RenderPptError("没装 python-pptx：pip install python-pptx") from None
    d = Path(project_dir)
    pptx_path = d / "output" / "卡片.pptx"
    pptx_path.parent.mkdir(parents=True, exist_ok=True)
    ratio = str(project.get("ratio") or "9:16")
    W, H = (Inches(7.5), Inches(13.333)) if ratio != "16:9" else (Inches(13.333), Inches(7.5))
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    blank = prs.slide_layouts[6]
    shots = [s for s in (project.get("shots") or []) if s.get("render") == "ppt"]
    for i, s in enumerate(shots, 1):
        slide = prs.slides.add_slide(blank)
        bg = slide.background.fill
        bg.solid()
        bg.fore_color.rgb = RGBColor(0x07, 0x0D, 0x16)
        # 左侧强调条
        bar = slide.shapes.add_shape(1, Inches(.55), Inches(.75), Inches(.12), H - Inches(1.5))
        bar.fill.solid()
        bar.fill.fore_color.rgb = RGBColor(0x38, 0xF2, 0xD0)
        bar.line.fill.background()
        role = slide.shapes.add_textbox(Inches(.9), Inches(.55), W - Inches(1.4), Inches(.6))
        p = role.text_frame.paragraphs[0]
        p.text = f"{s.get('role') or '旁白'} · 第 {str(s.get('id') or i).lstrip('s') or i} 镜"
        p.font.size = Pt(16)
        p.font.color.rgb = RGBColor(0x38, 0xF2, 0xD0)
        title = slide.shapes.add_textbox(Inches(.9), Inches(1.3), W - Inches(1.4), Inches(1.9))
        tf = title.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = re.sub(r"\s+", " ", str(s.get("text") or ""))[:80]
        p.font.size = Pt(30 if ratio != "16:9" else 26)
        p.font.bold = True
        p.font.color.rgb = RGBColor(0xF2, 0xFB, 0xFF)
        p.alignment = PP_ALIGN.LEFT
        pts = _points(s)
        body = slide.shapes.add_textbox(Inches(.9), Inches(3.6), W - Inches(1.4), H - Inches(4.8))
        bf = body.text_frame
        bf.word_wrap = True
        for j, x in enumerate(pts):
            p = bf.paragraphs[0] if j == 0 else bf.add_paragraph()
            p.text = "•  " + x[:90]
            p.font.size = Pt(22 if ratio != "16:9" else 20)
            p.font.color.rgb = RGBColor(0xC8, 0xDE, 0xEA)
            p.space_after = Pt(16)
        num = slide.shapes.add_textbox(W - Inches(1.2), H - Inches(.9), Inches(.7), Inches(.4))
        num.text_frame.paragraphs[0].text = f"{i:02d}"
        num.text_frame.paragraphs[0].font.size = Pt(12)
        num.text_frame.paragraphs[0].font.color.rgb = RGBColor(0x5F, 0x7D, 0x92)
    prs.save(str(pptx_path))
    return pptx_path


def _slide_html(shot, W, H, i):
    try:
        page = int(i)
    except (TypeError, ValueError):
        page = 1
    pts = "".join(f"<li>{_esc(x)}</li>" for x in _points(shot))
    role = _esc(shot.get("role") or "旁白")
    text = _esc(re.sub(r"\s+", " ", str(shot.get("text") or ""))[:100])
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
    *{{box-sizing:border-box}}html,body{{margin:0;width:{W}px;height:{H}px;overflow:hidden;background:#070d16;color:#eafaff;font-family:"Microsoft YaHei","PingFang SC",sans-serif}}
    body{{padding:{'7% 8%' if H>W else '6% 8%'};position:relative;background:
      radial-gradient(circle at 15% 10%,rgba(56,242,208,.16),transparent 32%),
      radial-gradient(circle at 85% 85%,rgba(74,140,255,.14),transparent 34%),#070d16}}
    .bar{{position:absolute;left:4.5%;top:8%;bottom:8%;width:8px;background:#38f2d0;border-radius:8px;box-shadow:0 0 24px rgba(56,242,208,.55)}}
    .cap{{font-size:{max(16,int(W*.018))}px;letter-spacing:.16em;color:#38f2d0;margin-bottom:4%}}
    h1{{font-size:{max(30,int(W*.045))}px;line-height:1.28;margin:0 0 7%;font-weight:800}}
    ul{{margin:0;padding-left:1.2em;display:flex;flex-direction:column;gap:2.2%}}
    li{{font-size:{max(20,int(W*.028))}px;line-height:1.55;color:#c8deea}}
    .num{{position:absolute;right:7%;bottom:5%;font-family:monospace;font-size:{max(14,int(W*.02))}px;color:#5f7d92}}
    .glass{{position:absolute;right:7%;top:9%;width:18%;aspect-ratio:1;border:1px solid rgba(56,242,208,.35);border-radius:50%;background:radial-gradient(circle,rgba(56,242,208,.14),transparent 65%)}}
    </style></head><body><div class="bar"></div><div class="glass"></div><div class="cap">{role} · 第 {page} 镜</div><h1>{text}</h1><ul>{pts}</ul><div class="num">{page:02d}</div></body></html>"""


def render_slide(project_dir, shot, out_path, W, H, page=1) -> Path:
    try:
        from playwright.sync_api import sync_playwright
        from .render_web import _open_browser
    except ImportError:
        raise RenderPptError("没装 Playwright：pip install playwright") from None
    d = Path(project_dir)
    render_dir = d / "render"
    render_dir.mkdir(parents=True, exist_ok=True)
    hp = render_dir / (Path(out_path).stem + ".html")
    hp.write_text(_slide_html(shot, W, H, page), "utf-8")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        br = _open_browser(pw)
        page_obj = br.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        page_obj.goto(hp.resolve().as_uri(), wait_until="load")
        page_obj.wait_for_timeout(220)
        page_obj.screenshot(path=str(out), type="png")
        br.close()
    return out


def _imported_slides(project_dir, project):
    """导入的 .pptx 用 soffice/libreoffice 转 PDF 再转图片；没有工具就返回 []。"""
    f = str((project.get("settings") or {}).get("ppt_file") or "").strip()
    if not f:
        return []
    p = Path(f)
    if not p.is_absolute():
        p = Path(project_dir) / p
    if not p.is_file():
        return []
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return []
    d = Path(project_dir) / "render" / "pptx_import"
    d.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(d), str(p)],
                       capture_output=True, timeout=180, creationflags=NOWIN)
        pdf = next(d.glob("*.pdf"), None)
        if not pdf:
            return []
        pdftoppm = shutil.which("pdftoppm")
        if not pdftoppm:
            return []
        subprocess.run([pdftoppm, "-png", "-r", "120", str(pdf), str(d / "slide")],
                       capture_output=True, timeout=180, creationflags=NOWIN)
        return sorted(d.glob("slide*.png"))
    except Exception:
        return []


def render_all(project_dir, project, say=None, stopped=None) -> dict:
    say = say or (lambda _m: None)
    d = Path(project_dir)
    ratio = str(project.get("ratio") or "9:16")
    W, H = (1080, 1920) if ratio != "16:9" else (1920, 1080)
    shots = [s for s in (project.get("shots") or []) if s.get("render") == "ppt"]
    if not shots:
        return {}
    try:
        auto_pptx(d, project)
    except RenderPptError:
        pass
    imported = _imported_slides(d, project)
    out = {}
    for i, s in enumerate(shots, 1):
        if stopped and stopped():
            raise RenderPptError("停下了")
        say(f"PPT 卡片渲染 {i}/{len(shots)}：第 {s.get('id')} 镜")
        p = d / "render" / f"ppt_{s['id']}.png"
        if i <= len(imported):
            shutil.copy2(imported[i - 1], p)
        else:
            render_slide(d, s, p, W, H, str(s.get('id') or i).lstrip('s') or i)
        s["render_image"] = f"render/{p.name}"
        out[s["id"]] = s["render_image"]
    return out
