#!/usr/bin/env python3
"""
제47회(2024) 보험업법·손해사정이론 PDF 복원.
이 두 PDF는 숫자·기호가 포함된 글줄 조각이 마스크 이미지로 들어 있어 텍스트 추출 시 숫자·괄호·문장부호가 빠진다.
  1) 텍스트 레이어(한글)는 그대로 쓰고
  2) 이미지 조각이 있는 줄은 Windows OCR 결과와 글자 단위로 정렬(difflib)하여, OCR에만 있는 숫자·기호만 끼워 넣는다(한글은 텍스트 레이어 우선)
  3) 문항번호·보기번호 마커는 좌표 규칙으로 복원한다

사용: python tools/fix47.py <pages47_ocr.json> [--dpi 300] [--dump 폴더]
"""
import argparse
import difflib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_kidi import parse_questions, parse_answer_table, SUBJECTS, BANK_DIR, PAGE_TAG_RE, HEADER_RE, RULE_RE  # noqa: E402
from import_pdf import build  # noqa: E402
import pymupdf  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
FILES = {
    "보험업법": ("data/raw/47/제47회 1차시험(사정사)_보험업법.pdf", "up"),
    "손해사정이론": ("data/raw/47/제47회 1차시험(사정사)_손해사정사이론.pdf", "th"),
}
CIRC = "①②③④⑤"
QMARK, CMARK = "⎕Q", "⎕C"
HANGUL = re.compile(r"[가-힣]")


def merge_digits(a: str, b: str) -> str:
    """a: 텍스트 레이어 줄(숫자 누락), b: OCR 줄. b에만 있는 비한글 문자를 a에 끼워 넣는다."""
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    out = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        aseg, bseg = a[i1:i2], b[j1:j2]
        if op in ("equal", "delete"):
            out.append(aseg)
        elif op == "insert":
            out.append("".join(c for c in bseg if not HANGUL.match(c)))
        else:  # replace
            extra = "".join(c for c in bseg if not HANGUL.match(c))
            if aseg.strip() == "":
                out.append(extra if extra.strip() else aseg)
            else:
                out.append(aseg + "".join(c for c in extra if c not in aseg and not c.isspace()))
    s = "".join(out)
    s = re.sub(r"[ ]{2,}", " ", s)
    return s.strip()


def clean_word(t):
    t = re.sub(r"[①-⑳㉠-㉿ⓐ-ⓩ❶-❿]", "", t).strip()
    if any(0x4E00 <= ord(c) <= 0x9FFF or 0xC0 <= ord(c) <= 0x24F or 0x3040 <= ord(c) <= 0x30FF for c in t):
        return ""
    if t in ("•", "·", "・", "'", "`", "‘", "’", "\"", "|", "l", "I", "ㅣ", "-", "—", "="):
        return ""
    return t


def page_rows(page, ocr_words, dpi):
    W = page.rect.width
    split = W * 0.47
    k = 72.0 / dpi
    ocr = []
    for w in ocr_words:
        t = clean_word(w["t"])
        raw = w["t"].strip()
        ocr.append({"cx": (w["x0"] + w["x1"]) / 2 * k, "cy": (w["y0"] + w["y1"]) / 2 * k, "x0": w["x0"] * k, "x1": w["x1"] * k, "t": t, "raw": raw})

    items = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            t = "".join(s["text"] for s in ln["spans"]).strip()
            if t:
                x0, y0, x1, y1 = ln["bbox"]
                items.append({"y0": y0, "y1": y1, "x0": x0, "x1": x1, "kind": "txt", "text": t})
    for info in page.get_image_info():
        r = pymupdf.Rect(info["bbox"])
        if r.width < 3 or r.height < 6 or r.height > 30 or r.width > W * 0.45 or r.y1 < 100:
            continue  # 머리글 띠, 괘선 제외
        col_left = r.x0 < split
        edge_q = 71.5 if col_left else 371.8
        edge_c = 81.0 if col_left else 381.4
        narrow = r.width <= 30
        inside = [w for w in ocr if r.x0 - 2 <= w["cx"] <= r.x1 + 2 and r.y0 - 2 <= w["cy"] <= r.y1 + 2]
        kind = "img"
        if abs(r.x0 - edge_q) <= 2.5:
            kind = "q"
        elif abs(r.x0 - edge_c) <= 2.5:
            kind = "c"
        items.append({"y0": r.y0, "y1": r.y1, "x0": r.x0, "x1": r.x1, "kind": kind, "wide": not narrow, "text": ""})
    lines_out = []
    for col in (0, 1):
        col_items = sorted([it for it in items if (it["x0"] < split) == (col == 0)], key=lambda it: (it["y0"], it["x0"]))
        rows = []
        for it in col_items:
            if rows and abs(rows[-1]["y"] - it["y0"]) <= 3.5:
                rows[-1]["items"].append(it)
            else:
                rows.append({"y": it["y0"], "items": [it]})
        for row in rows:
            its = sorted(row["items"], key=lambda it: it["x0"])
            y0 = min(it["y0"] for it in its); y1 = max(it["y1"] for it in its)
            # 한 줄에 보기 두 개가 놓인 편집: 큰 간격 뒤의 좁은 조각 + 바로 이어지는 텍스트 → 보기 마커
            for idx in range(1, len(its) - 1):
                it, prev, nxt = its[idx], its[idx - 1], its[idx + 1]
                if it["kind"] == "img" and (it["x1"] - it["x0"]) <= 26 and nxt["kind"] == "txt" \
                        and it["x0"] - prev["x1"] >= 8 and nxt["x0"] - it["x1"] <= 5:
                    it["kind"] = "c"; it["wide"] = False
            # 보기 두 개가 한 줄: 보기 행에서 큰 간격 뒤에 두 번째 열 위치(≈220/520pt)에서 시작하는 텍스트 앞에 마커 삽입
            if any(it["kind"] == "c" for it in its):
                second_x = 220 if col == 0 else 520
                extra = []
                for idx in range(1, len(its)):
                    it = its[idx]
                    prev_txt = [p for p in its[:idx] if p["kind"] == "txt"]
                    prev_x1 = max(p["x1"] for p in prev_txt) if prev_txt else 0
                    txt_count = sum(1 for p in its if p["kind"] == "txt")
                    if it["kind"] == "txt" and prev_txt and it["x0"] - prev_x1 >= 8 \
                            and (abs(it["x0"] - second_x) <= 40 or (txt_count == 2 and it["x0"] - prev_x1 >= 12)) \
                            and not any(p["kind"] == "c" and p["x0"] > 150 for p in its):
                        extra.append({"y0": it["y0"], "y1": it["y1"], "x0": it["x0"] - 1, "x1": it["x0"], "kind": "c", "wide": False, "text": ""})
                if extra:
                    its = sorted(its + extra, key=lambda it: it["x0"])
            tail = its[-1] if its[-1]["kind"] == "img" and its[-1]["x1"] - its[-1]["x0"] < 9 else None
            parts, need_ocr = [], False
            for it in its:
                if it["kind"] == "txt":
                    parts.append(it["text"])
                elif it["kind"] == "q":
                    parts.append(QMARK); need_ocr = need_ocr or it.get("wide")
                elif it["kind"] == "c":
                    parts.append(CMARK); need_ocr = need_ocr or it.get("wide")
                else:
                    need_ocr = True
            a = " ".join(parts).strip()
            if need_ocr:
                words = sorted([w for w in ocr if y0 - 2 <= w["cy"] <= y1 + 2 and ((w["cx"] < split) == (col == 0)) and w["t"]
                                and not (tail and tail["x0"] - 3 <= w["cx"] <= tail["x1"] + 3)], key=lambda w: w["x0"])
                bstr = " ".join(w["t"] for w in words)
                if QMARK in a:
                    bstr = re.sub(r"^\s*\d{1,2}(\s*\.)?\s+", "", bstr)
                a = merge_digits(a, bstr) if bstr else a
                a = re.sub(r"[\s•·・=]+$", "", a)
                last = its[-1]
                if last["kind"] == "img" and last["x1"] - last["x0"] < 9 and a and a[-1] not in "?.,)」":
                    a += "?" if re.search(r"(은|는|가|까|요|지)$", a) else "."
            a = PAGE_TAG_RE.sub("", a).strip()
            a = re.sub(r"(것은|것은가|하는가|인가|한가|않은|옳은|없는가|있는가)[0-9gq]{1,2}$", r"\1?", a)
            a = re.sub(r"(있는|없는|되는|하는|아닌|않은|옳은)[0-9]{1,2}(?=\s)", r"\1", a)
            if QMARK not in a and CMARK not in a:
                if not a or RULE_RE.match(a) or (HEADER_RE.search(a) and len(a) < 40) or re.fullmatch(r"[\s▢\d쪽\-–]*", a):
                    continue
            lines_out.append(a)
    return lines_out


def number_markers(text):
    out, qn, cn = [], 0, 0
    for ln in text.split("\n"):
        while QMARK in ln:
            qn += 1; cn = 0
            ln = ln.replace(QMARK, f"{qn}. ", 1)
        while CMARK in ln:
            ln = ln.replace(CMARK, CIRC[min(cn, 4)] + " ", 1); cn += 1
        ln = re.sub(r"^(\d{1,2})\. (\d{1,2})\. ", r"\1. ", ln)
        ln = re.sub(r" ([①②③④⑤]) \.\s*", r". \1 ", ln)
        out.append(re.sub(r"\s{2,}", " ", ln))
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ocr_json")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--dump")
    a = ap.parse_args()
    ocr = json.load(open(a.ocr_json, encoding="utf-8-sig"))
    answers = parse_answer_table(ROOT / "data/raw/47/제47회 1차시험 확정답안.pdf")
    for subj, (rel, tag) in FILES.items():
        doc = pymupdf.open(ROOT / rel)
        text = []
        for pi, page in enumerate(doc):
            words = ocr.get(f"{tag}_{pi:02d}.png", [])
            if isinstance(words, dict):
                words = [words]
            text.extend(page_rows(page, words, a.dpi))
            text.append("")
        full = number_markers("\n".join(text))
        if a.dump:
            Path(a.dump).mkdir(parents=True, exist_ok=True)
            (Path(a.dump) / f"47_{subj}.txt").write_text(full, encoding="utf-8")
        qs = parse_questions(full)
        out = []
        for q in qs:
            acc = answers[subj].get(q["num"], [])
            rec = {
                "id": f"2024-47-{SUBJECTS.index(subj)}-{q['num']}", "year": 2024, "round": 47, "subject": subj, "num": q["num"],
                "question": q["question"], "choices": q["choices"], "answer": acc[0] if acc else 0,
                "explanation": "", "source": "보험개발원 제47회 (숫자 OCR 보정)",
            }
            if len(acc) > 1:
                rec["accept"] = acc
            out.append(rec)
        BANK_DIR.mkdir(parents=True, exist_ok=True)
        (BANK_DIR / f"2024_47_{subj}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        short = [q["num"] for q in out if len([c for c in q["choices"] if c]) < 4]
        print(f"[저장] 2024_47_{subj}.json: {len(out)}문항, 보기부족 {short}")
    build()


if __name__ == "__main__":
    main()
