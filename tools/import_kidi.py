#!/usr/bin/env python3
"""
보험개발원(KIDI) 배포 손해사정사 1차 기출문제 zip 전용 임포터.

  python tools/import_kidi.py data/raw/49 --round 49 --year 2026
  python tools/import_kidi.py data/raw/44 data/raw/45 ... (--round/--year 생략 시 폴더명(회차)에서 추정, 연도 = 회차 + 1977)

폴더 안에서 파일명에 '사정사' 또는 과목명이 들어간 문제 PDF와 '확정답안'/'답안' PDF를 찾아
  - 2단(B4 가로) 편집 문제 PDF를 좌/우 단으로 나눠 읽고
  - 확정답안 표(보험계리사 4열 + 손해사정사 3열)에서 손해사정사 열만 골라
data/bank/{year}_{round}_{subject}.json 을 만든 뒤 data/questions.js 를 다시 빌드한다.
복수정답("2,3,4") 및 전항정답("1,2,3,4")은 accept 배열로 저장한다.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_pdf import BANK_DIR, SUBJECTS, CIRCLED_MAP, build  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

try:
    import pymupdf
except ImportError:  # pragma: no cover
    import fitz as pymupdf

ROOT = Path(__file__).resolve().parent.parent
HEADER_RE = re.compile(r"(손해사정사\s*시험|보험전문인|1차\s*시험|^\s*(보험업법|보험계약법|손해사정이론)\s*$)")
PAGE_TAG_RE = re.compile(r"\s*(손해사정사시험)?\s*[–\-]?\s*(보험업법|보험계약법|손해사정이론)?\s*[–\-]\s*\d+\s*쪽")
RULE_RE = re.compile(r"^[━─—\-=_\s]{5,}$")
Q_START = re.compile(r"^\s*(\d{1,2})\s*[.．](?:\s+|$)")


# ---------- 2단 PDF 텍스트 ----------
def column_text(pdf: Path) -> str:
    doc = pymupdf.open(pdf)
    out = []
    for page in doc:
        W = page.rect.width
        split = W * 0.47
        cols = {0: [], 1: []}
        for b in page.get_text("dict")["blocks"]:
            for ln in b.get("lines", []):
                txt = "".join(s["text"] for s in ln["spans"]).strip()
                if not txt:
                    continue
                x0, y0 = ln["bbox"][0], ln["bbox"][1]
                cols[0 if x0 < split else 1].append((round(y0), x0, txt))
        for c in (0, 1):
            lines = sorted(cols[c])
            # 같은 y(±3)의 조각은 x순으로 한 줄로 합침
            merged = []
            for y, x, t in lines:
                if merged and abs(merged[-1][0] - y) <= 3:
                    merged[-1] = (merged[-1][0], merged[-1][1], merged[-1][2] + " " + t)
                else:
                    merged.append((y, x, t))
            for y, x, t in merged:
                t = PAGE_TAG_RE.sub("", t).strip()
                if not t or (HEADER_RE.search(t) and len(t) < 40):
                    continue
                if RULE_RE.match(t):
                    continue
                out.append(t)
        out.append("")  # 페이지 경계
    return "\n".join(out)


def parse_questions(text: str):
    # 보기 기호 앞 줄바꿈 보장
    text = re.sub(r"[ \t]*([①②③④⑤])[ \t]*", r"\n\1 ", text)
    lines = [ln.strip() for ln in text.split("\n")]
    questions, cur, expect = [], None, 1
    for ln in lines:
        if not ln:
            continue
        m = Q_START.match(ln)
        if m and int(m.group(1)) == expect:
            cur = {"num": expect, "stem": [ln[m.end():].strip()], "choices": [], "ci": None}
            questions.append(cur); expect += 1
            continue
        if cur is None:
            continue
        if ln[0] in CIRCLED_MAP and CIRCLED_MAP[ln[0]] == (cur["ci"] or 0) + 1:
            ci = CIRCLED_MAP[ln[0]]
            cur["choices"].append(ln[1:].strip())
            cur["ci"] = ci
        elif ln[0] in CIRCLED_MAP and cur["ci"] is not None:
            cur["choices"][cur["ci"] - 1] = join_wrap(cur["choices"][cur["ci"] - 1], ln)
        elif cur["ci"] is None:
            cur["stem"].append(ln)
        else:
            # 보기 ④ 이후에 이어지는 줄: 다음 문제 시작이 아니면 마지막 보기의 연속
            cur["choices"][cur["ci"] - 1] = join_wrap(cur["choices"][cur["ci"] - 1], ln)
    for q in questions:
        q["question"] = clean_stem(q.pop("stem"))
        q["choices"] = [re.sub(r"\s+", " ", c).strip() for c in q["choices"][:5]]
        q.pop("ci", None)
    return questions


HANGUL = re.compile(r"[가-힣]")


def join_wrap(prev: str, nxt: str) -> str:
    """PDF 줄바꿈 이어붙이기: 한글 음절 사이에서 끊긴 경우 공백 없이 붙인다."""
    prev, nxt = prev.rstrip(), nxt.lstrip()
    if not prev:
        return nxt
    if HANGUL.match(prev[-1]) and HANGUL.match(nxt[:1]):
        # 한글-한글 줄바꿈: 띄어쓰기 여부를 tools/respace.py(형태소 분석)가 나중에 판단하도록 표식을 남긴다
        return prev + WRAP_SEP + nxt
    return prev + " " + nxt


WRAP_SEP = "⁣"


WRAP_SPACE_ENDINGS = set("은는이가을를의에로과와도서게고며면여어아다한된될등및중시후전내외상각그때만")


def clean_stem(parts):
    # 문제 본문: 첫 줄 + 이어지는 줄. <보기> 상자(ㄱ. ㄴ. ㄷ.)는 줄바꿈 유지
    keep = re.compile(r"^([ㄱ-ㅎ]\s*[.．)]|[가-힣]\s*[.．)]\s|<|\(|[A-Z]\s*[.．)]|[-·•ㆍ])")
    out = ""
    for ln in parts:
        ln = re.sub(r"[ \t]+", " ", ln).strip()
        if not ln:
            continue
        if not out:
            out = ln
        elif keep.match(ln) or out.endswith("?"):
            out += "\n" + ln
        else:
            out = join_wrap(out, ln)
    return out.strip()


# ---------- 확정답안 표 ----------
def parse_answer_table(pdf: Path):
    """9열(계리사 번호+4과목, 손사 번호+3과목) 표에서 손사 3과목 정답을 읽는다. 반환: {subject: {num: [answers]}}"""
    page = pymupdf.open(pdf)[0]
    words = [w for w in page.get_text("words") if re.fullmatch(r"[1-5]([.,][1-5])*", w[4]) or re.fullmatch(r"\d{1,2}", w[4])]
    # 행 클러스터링(y)
    words.sort(key=lambda w: (w[1], w[0]))
    rows, cur, last_y = [], [], None
    for w in words:
        if last_y is None or abs(w[1] - last_y) <= 7:
            cur.append(w)
        else:
            rows.append(cur); cur = [w]
        last_y = w[1]
    if cur:
        rows.append(cur)
    # 열 중심 x 클러스터링
    xs = sorted((w[0] + w[2]) / 2 for r in rows for w in r)
    centers = []
    for x in xs:
        if centers and abs(centers[-1][-1] - x) <= 12:
            centers[-1].append(x)
        else:
            centers.append([x])
    centers = [sum(c) / len(c) for c in centers if len(c) >= 10]
    if len(centers) < 4:
        raise RuntimeError(f"답안표 열을 찾지 못함: {pdf.name} centers={centers}")
    # 9열(번호+계리사4+번호+손사3) 또는 8열(번호+계리사4+손사3) 레이아웃 모두 지원
    sonsa_cols = centers[-4:] if len(centers) >= 9 else [centers[0]] + centers[-3:]
    result = {s: {} for s in SUBJECTS}
    for r in rows:
        cells = {}
        for w in r:
            cx = (w[0] + w[2]) / 2
            j = min(range(len(sonsa_cols)), key=lambda k: abs(sonsa_cols[k] - cx))
            if abs(sonsa_cols[j] - cx) <= 12:
                cells[j] = w[4]
        if 0 in cells and cells[0].isdigit():
            num = int(cells[0])
            for k, s in enumerate(SUBJECTS, start=1):
                if k in cells:
                    result[s][num] = [int(a) for a in re.split(r"[.,]", cells[k])]
    return result


# ---------- HWP 텍스트(2016~2017) / xls 정답 ----------
def hwp_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-16", "utf-8-sig", "cp949"):
        try:
            t = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        if chr(9312) in t or "1." in t:
            return t.replace(chr(13) + chr(10), chr(10)).replace(chr(13), chr(10))
    return raw.decode("utf-8", errors="ignore")


def parse_answer_xls(path: Path):
    """구분 | 계리사 4열 | 손사 3열(업법, 계약법, 이론) 형태의 확정답안 xls"""
    import xlrd
    sh = xlrd.open_workbook(str(path)).sheet_by_index(0)
    result = {s: {} for s in SUBJECTS}
    for r in range(sh.nrows):
        first = str(sh.cell_value(r, 0)).strip()
        try:
            num = int(float(first))
        except ValueError:
            continue
        cols = sh.ncols
        for k, subj in enumerate(SUBJECTS):
            v = str(sh.cell_value(r, cols - 3 + k)).strip()
            if not v:
                continue
            result[subj][num] = [int(float(a)) for a in re.split(r"[.,]", v) if a.strip()] if "," in v else [int(float(v))]
    return result


# ---------- 폴더 처리 ----------
def guess_subject(name: str):
    if "업법" in name:
        return "보험업법"
    if "계약법" in name:
        return "보험계약법"
    if "이론" in name or "손사" in name:
        return "손해사정이론"
    return None


def process(folder: Path, rnd: int, year: int):
    pdfs = sorted(folder.glob("*.pdf")) + sorted(folder.glob("*.txt"))
    ans_pdf = next((p for p in pdfs if "답안" in p.name), None)
    ans_xls = next(iter(sorted(folder.glob("*답안*.xls*"))), None)
    if ans_pdf:
        answers = parse_answer_table(ans_pdf)
    elif ans_xls:
        answers = parse_answer_xls(ans_xls)
    else:
        answers = {s: {} for s in SUBJECTS}
    src = ans_pdf or ans_xls
    if src:
        print(f"[답안] {src.name}: " + ", ".join(f"{s} {len(v)}" for s, v in answers.items()))
    BANK_DIR.mkdir(parents=True, exist_ok=True)
    for p in pdfs:
        if p is ans_pdf or "계리사" in p.name or "근퇴법" in p.name or "경제학" in p.name or "수학" in p.name or "회계" in p.name:
            continue
        subj = guess_subject(p.name)
        if not subj:
            print(f"  - 과목 불명, 건너뜀: {p.name}"); continue
        qs = parse_questions(hwp_text(p) if p.suffix == ".txt" else column_text(p))
        out = []
        for q in qs:
            acc = answers[subj].get(q["num"], [])
            out.append({
                "id": f"{year}-{rnd}-{SUBJECTS.index(subj)}-{q['num']}",
                "year": year, "round": rnd, "subject": subj, "num": q["num"],
                "question": q["question"], "choices": q["choices"],
                "answer": acc[0] if acc else 0,
                "accept": acc if len(acc) > 1 else None,
                "explanation": "",
                "source": f"보험개발원 제{rnd}회",
            })
        for o in out:
            if o["accept"] is None:
                o.pop("accept")
        path = BANK_DIR / f"{year}_{rnd}_{subj}.json"
        path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        short = [q["num"] for q in out if len([c for c in q["choices"] if c]) < 4]
        noans = [q["num"] for q in out if not q["answer"]]
        flag = "" if len(out) == 40 and not short and not noans else "  <-- 확인 필요"
        print(f"[저장] {path.name}: {len(out)}문항, 보기부족 {short}, 정답없음 {noans}{flag}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folders", nargs="+")
    ap.add_argument("--round", type=int, dest="rnd")
    ap.add_argument("--year", type=int)
    ap.add_argument("--no-build", action="store_true")
    a = ap.parse_args()
    for f in a.folders:
        folder = Path(f)
        m = re.search(r"(\d{2})", folder.name)
        rnd = a.rnd or (int(m.group(1)) if m else None)
        year = a.year or (rnd + 1977 if rnd else None)   # 제49회 = 2026년
        if not rnd or not year:
            sys.exit(f"회차/연도를 알 수 없음: {folder}")
        print(f"===== 제{rnd}회 ({year}년) {folder}")
        process(folder, rnd, year)
    if not a.no_build:
        build()


if __name__ == "__main__":
    main()
