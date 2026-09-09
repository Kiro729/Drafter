#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
연구계획서 md(+ 다이어그램 png) → 디자인 적용 PDF

  python3 build.py --md input/proposal.md --out build/proposal.pdf

동작 개요
  1) markdown-it 로 md → 소박한 HTML
  2) BeautifulSoup 로 의미 구조 부여
       - h2/h3 자동 번호, 모듈(h4) 카드화
       - '라벨 + 하위 불릿' 패턴을 정의형 블록으로 재구성
       - [그림 n] 불릿 → <figure> + 실제 이미지
       - [Author et al., YYYY] → 참고문헌 링크 배지
  3) 표지 / 목차 / 본문 세 개의 HTML 로 분리 렌더 (Chromium)
  4) 본문 PDF 에서 각 제목의 실제 페이지를 역추적해 목차 페이지 번호 확정
  5) 세 PDF 를 병합
"""

import argparse
import base64
import json
import logging
import pathlib
import re
import sys
import unicodedata

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt
from playwright.sync_api import sync_playwright
from pypdf import PdfWriter, PdfReader
import pdfplumber

logging.getLogger("pdfminer").setLevel(logging.ERROR)     # 목차 페이지를 되읽을 때 나오는 FontBBox 경고 억제

HERE = pathlib.Path(__file__).parent.resolve()


def _resolve(p) -> pathlib.Path:
    """절대경로는 그대로, 상대경로는 이 파일 기준."""
    p = pathlib.Path(p)
    return p if p.is_absolute() else HERE / p

# ============================================================
# 표지/머리글에 들어가는 문서 메타. 시스템에서 넘겨줄 값들.
# ============================================================
DEFAULT_META = {
    "kicker": "연구계획서",
    "kicker_en": "RESEARCH PROPOSAL",
    # 부제·키워드·작성자는 export_pdf 가 meta.json 으로 넘긴다. 기본값은 비워 두어 예시 값이 표지에 새지 않게 한다.
    "subtitle": "",
    "keywords": [],
    "meta_rows": [],
    "running_header": "",
    # 장(chapter)마다 새 페이지에서 시작할지. False 면 페이지가 촘촘해지는 대신
    # 장 제목이 페이지 중간에서 시작한다.
    "chapter_page_break": True,
    # [그림 n] → 이미지 경로
    "figures": {"1": "input/figure1.png"},
}

# chapter_page_break 를 끌 때 덧붙이는 CSS
DENSE_CSS = "\n.body .chapter { break-before: auto; margin-top: 14mm; }\n"

PAGE = {"format": "A4", "print_background": True,
        "margin": {"top": "0", "bottom": "0", "left": "0", "right": "0"}}

# 본문 페이지 기하 (assets/style.css 의 @page body-page 와 반드시 일치시킬 것)
MARGIN_TOP, MARGIN_BOT, MARGIN_SIDE = 22, 20, 22
CONTENT_W = 210 - MARGIN_SIDE * 2          # 166mm
CONTENT_H = 297 - MARGIN_TOP - MARGIN_BOT  # 255mm


# ============================================================
# 유틸
# ============================================================
def norm(s: str) -> str:
    """공백·제어문자 전부 제거 + NFC 정규화 (PDF 텍스트 대조용)

    Chromium 이 심는 서브셋 폰트는 제목의 공백을 ToUnicode 에 매핑하지 않는
    경우가 있어 pdfplumber 가 이를 U+0000 으로 뽑아낸다. `\\s` 만 지우면
    '연구\\x00배경' 이 '연구배경' 과 달라져 목차 쪽번호가 전부 빗나간다.
    그래서 제어문자(Cc)·서식문자(Cf)·공백류(Zs)도 함께 제거한다.
    """
    text = unicodedata.normalize("NFC", s or "")
    return "".join(
        ch for ch in text
        if not ch.isspace() and unicodedata.category(ch) not in ("Cc", "Cf", "Zs")
    )


def data_uri(path: pathlib.Path) -> str:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


# ============================================================
# 1. markdown → html
# ============================================================
def md_to_html(md_text: str) -> str:
    # 줄 끝 공백 제거: md 의 trailing double-space 가 <br> 로 새는 것을 방지
    cleaned = "\n".join(line.rstrip() for line in md_text.splitlines())
    md = MarkdownIt("commonmark").enable("table")
    return md.render(cleaned)


# ============================================================
# 2. 구조화
# ============================================================
CITE_RE = re.compile(r"\[([A-Z][A-Za-z\-']+(?:\s+et\s+al\.)?,?\s*\d{4})\]")
FIG_RE = re.compile(r"^\[그림\s*(\d+)\]\s*(.*)$", re.S)


def build_reference_index(ref_items):
    """참고문헌 li 목록 → {'ge2018': (번호, anchor id)}"""
    index = {}
    for i, li in enumerate(ref_items, start=1):
        text = li.get_text(" ", strip=True)
        m = re.match(r"\s*([A-Z][A-Za-z\-']+)", text)
        y = re.search(r"\((\d{4})\)", text)
        if m and y:
            index[(m.group(1).lower(), y.group(1))] = (i, f"ref-{m.group(1).lower()}{y.group(1)}")
    return index


def linkify_citations(soup, container, ref_index):
    """[Ge et al., 2018] → 배지 (+ 가능하면 참고문헌 앵커로 링크)"""
    for node in list(container.find_all(string=CITE_RE)):
        if node.find_parent(class_="references"):
            continue
        parts, last = [], 0
        raw = str(node)
        for m in CITE_RE.finditer(raw):
            if m.start() > last:
                parts.append(soup.new_string(raw[last:m.start()]))
            label = m.group(1)
            sm = re.match(r"([A-Za-z\-']+)", label)
            ym = re.search(r"(\d{4})", label)
            key = (sm.group(1).lower(), ym.group(1)) if sm and ym else None
            hit = ref_index.get(key)
            tag = soup.new_tag("a", href=f"#{hit[1]}") if hit else soup.new_tag("span")
            tag["class"] = "cite"
            tag.string = label
            parts.append(tag)
            last = m.end()
        if last < len(raw):
            parts.append(soup.new_string(raw[last:]))
        node.replace_with(*parts)


def restructure(html: str, meta: dict):
    """소박한 HTML → 표지용 조각 + 본문 HTML + 목차 트리"""
    soup = BeautifulSoup(html, "html.parser")

    # --- 제목 ---
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else "제목 없음"
    if h1:
        h1.decompose()

    # --- 최상위 노드를 h2 기준으로 chapter 단위로 묶기 ---
    nodes = [n for n in soup.contents if getattr(n, "name", None)]
    chapters, current = [], None
    for n in nodes:
        if n.name == "h2":
            current = {"h2": n, "nodes": []}
            chapters.append(current)
        elif current is not None:
            current["nodes"].append(n)

    abstract_html = ""
    body = BeautifulSoup("", "html.parser")
    # toc 는 아래에서 문서 순서대로 생성
    chapter_no = 0
    sub_seq = 0

    for ch in chapters:
        raw_title = ch["h2"].get_text(strip=True)
        # 'N. 제목' 형태면 번호를 떼고 자동 번호로 통일
        stripped = re.sub(r"^\d+\.\s*", "", raw_title)

        # 연구 요약 → 표지로
        if stripped in ("연구 요약", "요약", "초록"):
            paras = "".join(str(n) for n in ch["nodes"] if n.name == "p")
            abstract_html = (
                '<section class="cover-abstract">'
                f"<h2>{stripped}</h2>{paras}</section>"
            )
            continue

        is_ref = stripped in ("참고문헌", "References")
        if not is_ref:
            chapter_no += 1
            num = str(chapter_no)
        else:
            num = ""

        sec = soup.new_tag("section")
        sec["class"] = "chapter"
        sec["id"] = f"ch-{chapter_no if not is_ref else 'ref'}"

        h2 = soup.new_tag("h2")
        if num:
            sp = soup.new_tag("span"); sp["class"] = "num"; sp.string = num
            h2.append(sp)
        h2.append(soup.new_string(stripped))
        h2["data-no"] = num
        h2["data-title"] = stripped
        sec.append(h2)

        sub_no = 0
        module_no = 0
        for n in ch["nodes"]:
            if n.name == "h3":
                sub_no += 1
                t = n.get_text(strip=True)
                n.clear()
                sp = soup.new_tag("span"); sp["class"] = "num"
                sp.string = f"{num}.{sub_no}"
                n.append(sp)
                n.append(soup.new_string(t))
                n["data-no"] = f"{num}.{sub_no}"
                n["data-title"] = t
            sec.append(n.extract())

        # --- h4(모듈) 를 카드로 감싸기 ---
        h4s = sec.find_all("h4")
        for h4 in h4s:
            module_no += 1
            t = h4.get_text(strip=True)
            m = re.match(r"모듈\s*(\d+)\s*[:：]\s*(.*)", t)
            badge = f"M{m.group(1)}" if m else f"M{module_no}"
            label = m.group(2) if m else t

            card = soup.new_tag("section")
            card["class"] = "module"
            h4.insert_before(card)

            h4.clear()
            sp = soup.new_tag("span"); sp["class"] = "mnum"; sp.string = badge
            h4.append(sp)
            h4.append(soup.new_string(label))

            # h4 부터 다음 h4 직전까지 카드 안으로 이동
            sib = h4
            movers = [h4]
            while True:
                sib = sib.find_next_sibling()
                if sib is None or sib.name in ("h4", "h3", "h2"):
                    break
                movers.append(sib)
            for mv in movers:
                card.append(mv.extract())

            h4["data-no"] = badge
            h4["data-title"] = label

        # --- h3 단위로 subsection 래핑 (페이지 나눔 제어의 기본 단위) ---
        group = None
        for child in list(sec.children):
            if getattr(child, "name", None) is None:
                continue
            if child.name == "h3":
                sub_seq += 1
                group = soup.new_tag("section")
                group["class"] = "subsection"
                group["id"] = f"sub-{sub_seq}"
                child.insert_before(group)
                group.append(child.extract())
            elif group is not None and child.name != "h2":
                group.append(child.extract())

        body.append(sec)

    # --- 목록 클래스 / 라벨 처리 ---
    for ul in body.find_all("ul"):
        depth = len(ul.find_parents("ul"))
        ul["class"] = ["l1"] if depth == 0 else ["l2"]

    # 하위 목록을 가진 항목의 머리 텍스트를 lead 로 분리.
    #   짧으면(<= LABEL_MAX 자) '라벨'로, 길면 일반 문장으로 렌더한다.
    LABEL_MAX = 30
    for li in body.select("ul.l1 > li"):
        sub = li.find("ul", recursive=False)
        if not sub:
            continue
        li["class"] = ["has-sub"]
        lead = soup.new_tag("span")
        for node in list(li.contents):
            if node is sub:
                break
            lead.append(node.extract())
        plain = lead.get_text(" ", strip=True)
        lead["class"] = ["lead"] if len(plain) <= LABEL_MAX else ["lead", "lead-sentence"]
        li.insert(0, lead)

    # --- 참고문헌 ---
    ref_sec = body.find("section", id="ch-ref")
    ref_index = {}
    if ref_sec:
        ul = ref_sec.find("ul")
        if ul:
            ul["class"] = ["references"]
            items = ul.find_all("li", recursive=False)
            ref_index = build_reference_index(items)
            for i, li in enumerate(items, start=1):
                text = li.get_text(" ", strip=True)
                m = re.match(r"\s*([A-Z][A-Za-z\-']+)", text)
                y = re.search(r"\((\d{4})\)", text)
                if m and y:
                    li["id"] = f"ref-{m.group(1).lower()}{y.group(1)}"
                n = soup.new_tag("span"); n["class"] = "n"; n.string = f"[{i}]"
                li.insert(0, n)
                # URL 을 링크로
                for s in list(li.find_all(string=re.compile(r"https?://"))):
                    raw = str(s)
                    mm = re.search(r"(https?://\S+)", raw)
                    if not mm:
                        continue
                    a = soup.new_tag("a", href=mm.group(1))
                    a.string = mm.group(1)
                    s.replace_with(soup.new_string(raw[:mm.start()]), a,
                                   soup.new_string(raw[mm.end():]))

    # --- 목차는 모든 재구성이 끝난 뒤 문서 순서대로 수집한다.
    #     (모듈 카드가 h3 뒤로 옮겨지므로 중간에 만들면 순서가 어긋난다)
    LEVEL = {"h2": 1, "h3": 2, "h4": 3}
    toc = [{"level": LEVEL[el.name],
            "no": el.get("data-no", ""),
            "title": el.get("data-title", el.get_text(strip=True))}
           for el in body.find_all(["h2", "h3", "h4"])]

    linkify_citations(soup, body, ref_index)

    # --- [그림 n] 불릿 → figure ---
    for li in list(body.find_all("li")):
        m = FIG_RE.match(li.get_text(" ", strip=True))
        if not m:
            continue
        no, caption = m.group(1), m.group(2).strip()
        parent_ul = li.find_parent("ul")
        li.decompose()

        fig = soup.new_tag("figure")
        path = meta["figures"].get(no)
        if path and _resolve(path).exists():
            img = soup.new_tag("img", src=data_uri(_resolve(path)))
            fig.append(img)
        cap = soup.new_tag("figcaption")
        b = soup.new_tag("b"); b.string = f"그림 {no}."
        cap.append(b)
        cap.append(soup.new_string(" " + caption))
        fig.append(cap)

        anchor = parent_ul
        while anchor is not None and anchor.parent is not None and \
                anchor.parent.name == "li":
            anchor = anchor.find_parent("ul")
        anchor.insert_after(fig)
        if not parent_ul.find("li"):
            parent_ul.decompose()

    return title, abstract_html, body, toc


# ============================================================
# 3. HTML 조립
# ============================================================
def page_shell(css: str, inner: str) -> str:
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8">'
            f"<style>{css}</style></head><body>{inner}</body></html>")


def cover_html(css, meta, title, abstract_html):
    kws = "".join(f'<span class="kw">{k}</span>' for k in meta["keywords"])
    rows = "".join(
        f'<div class="row"><span class="k">{k}</span><span class="v">{v}</span></div>'
        for k, v in meta["meta_rows"])
    inner = f"""
<div class="cover">
  <div class="cover-rule-top"></div>
  <div class="cover-kicker">{meta['kicker']}<span class="sep">/</span>{meta['kicker_en']}</div>
  <h1 class="cover-title">{title}</h1>
  <p class="cover-subtitle">{meta['subtitle']}</p>
  <div class="keywords">{kws}</div>
  {abstract_html}
  <div class="cover-meta">{rows}</div>
</div>"""
    return page_shell(css, inner)


def toc_html(css, entries):
    rows = []
    for e in entries:
        lv = f"lv{e['level']}"
        pg = e.get("page", "")
        rows.append(
            f'<li class="{lv}"><span class="no">{e["no"]}</span>'
            f'<span class="ttl">{e["title"]}</span>'
            f'<span class="dots"></span><span class="pg">{pg}</span></li>')
    inner = ('<div class="toc"><h1 class="toc-head">목 차</h1><ol>'
             + "".join(rows) + "</ol></div>")
    return page_shell(css, inner)


def body_html(css, body):
    return page_shell(css, f'<div class="body">{body}</div>')


# ============================================================
# 4. 렌더
# ============================================================
# 본문 머리글은 사용하지 않는다. 빈 템플릿을 넘겨야 Chromium 기본 머리글
# (문서 제목 / 날짜 / URL)이 찍히지 않는다.
HDR = "<span></span>"

# Chromium 은 footer 템플릿을 본문과 다른 배율로 렌더한다(대략 0.6배).
# 따라서 원하는 크기의 1.6배 정도로 지정한다.
FTR = ('<div style="width:100%;font-family:\'Noto Sans CJK KR\',sans-serif;'
       'font-size:13pt;color:#7d868f;padding:0 22mm 11mm;text-align:center;'
       'font-variant-numeric:tabular-nums;">'
       '<span class="pageNumber"></span></div>')


def render(page, html, out_path, header=None, footer=None):
    page.set_content(html, wait_until="load")
    page.emulate_media(media="print")
    opts = dict(PAGE)
    if header or footer:
        opts = dict(PAGE)
        opts["margin"] = {"top": f"{MARGIN_TOP}mm", "bottom": f"{MARGIN_BOT}mm",
                          "left": "0mm", "right": "0mm"}
        opts["display_header_footer"] = True
        opts["header_template"] = header or "<span></span>"
        opts["footer_template"] = footer or "<span></span>"
    page.pdf(path=str(out_path), **opts)


def mark_unbreakable(page, css, body, fill=0.95):
    """
    각 소절(.subsection)의 실제 렌더 높이를 재서, 한 페이지 안에 들어가는 것만
    'keep' 클래스를 붙여 통째로 유지한다.

    CSS 의 break-inside:avoid 를 전부에 걸면 한 페이지를 넘는 소절이 통째로
    다음 장으로 밀려 큰 여백이 생긴다. 높이를 미리 재서 선별하면 그 부작용이
    없다. mm 는 절대 단위라 화면 렌더에서 잰 높이가 인쇄 높이와 일치한다.
    """
    probe_css = css + f"\n.body {{ width: {CONTENT_W}mm; }}\n"
    page.set_content(page_shell(probe_css, f'<div class="body">{body}</div>'),
                     wait_until="load")
    data = page.evaluate(
        """(mm) => {
            const ruler = document.createElement('div');
            ruler.style.height = mm + 'mm';
            document.body.appendChild(ruler);
            const limit = ruler.getBoundingClientRect().height;
            ruler.remove();
            const h = {};
            document.querySelectorAll('.subsection').forEach(
                el => h[el.id] = el.getBoundingClientRect().height);
            return {limit, h};
        }""", CONTENT_H)

    limit = data["limit"] * fill
    kept = 0
    for el in body.find_all("section", class_="subsection"):
        if data["h"].get(el.get("id"), 1e9) <= limit:
            el["class"] = ["subsection", "keep"]
            kept += 1
    return kept, len(data["h"])


def heading_pages(body_pdf: pathlib.Path, entries):
    """본문 PDF 에서 각 제목이 처음 등장하는 페이지를 순차 탐색."""
    with pdfplumber.open(body_pdf) as pdf:
        pages = [norm(p.extract_text() or "") for p in pdf.pages]
    cursor = 0
    for e in entries:
        needle = norm(e["title"])
        found = None
        for i in range(cursor, len(pages)):
            if needle and needle in pages[i]:
                found = i
                break
        if found is None:
            found = cursor
        e["page"] = found + 1
        cursor = found
    return entries


# ============================================================
# main
# ============================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", default="input/proposal.md")
    ap.add_argument("--out", default="build/proposal.pdf")
    ap.add_argument("--meta", default=None, help="메타 정보 JSON 경로 (선택)")
    ap.add_argument("--build-dir", default=None, help="중간 산출물 폴더 (기본 build/)")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):            # 한글 Windows 콘솔(cp949)에서도 경로·기호 출력이 죽지 않게
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    meta = dict(DEFAULT_META)
    if args.meta:
        meta.update(json.loads(pathlib.Path(args.meta).read_text("utf-8")))

    css = (HERE / "assets" / "style.css").read_text("utf-8")
    if not meta.get("chapter_page_break", True):
        css += DENSE_CSS
    md_text = _resolve(args.md).read_text("utf-8")

    title, abstract, body, toc = restructure(md_to_html(md_text), meta)

    tmp = pathlib.Path(args.build_dir) if args.build_dir else HERE / "build"
    tmp.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        kept, total = mark_unbreakable(page, css, body)
        print(f"  · 소절 {total}개 중 {kept}개를 한 페이지 안에 고정")

        body_src = str(body)
        (tmp / "_body.html").write_text(body_html(css, body_src), "utf-8")
        (tmp / "_cover.html").write_text(
            cover_html(css, meta, title, abstract), "utf-8")

        render(page, body_html(css, body_src), tmp / "_body.pdf", footer=FTR)
        heading_pages(tmp / "_body.pdf", toc)

        render(page, cover_html(css, meta, title, abstract), tmp / "_cover.pdf")
        render(page, toc_html(css, toc), tmp / "_toc.pdf")
        browser.close()

    writer = PdfWriter()
    for part in ("_cover.pdf", "_toc.pdf", "_body.pdf"):
        for pg in PdfReader(tmp / part).pages:
            writer.add_page(pg)
    writer.add_metadata({"/Title": title, "/Subject": meta["kicker"]})

    out = _resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as f:
        writer.write(f)
    print(f"OK {out}  ({len(writer.pages)} pages)")


if __name__ == "__main__":
    main()
