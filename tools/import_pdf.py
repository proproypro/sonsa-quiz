#!/usr/bin/env python3
"""
보험개발원 손해사정사 1차 기출문제 파일(PDF 또는 텍스트)을 문제은행 JSON으로 변환한다.

사용법
  python tools/import_pdf.py --year 2025 --round 48 --subject 보험계약법 --questions data/raw/48_계약법.pdf --answers data/raw/48_정답.pdf
  python tools/import_pdf.py --year 2025 --round 48 --auto data/raw/48회/        # 폴더 안 파일명으로 과목 자동 추정
  python tools/import_pdf.py --build                                            # data/bank/*.json 을 합쳐 data/questions.js(.json) 생성

동작
  1) PDF 텍스트를 추출(pymupdf)한 뒤 "N." 으로 시작하는 문제 블록과 ①②③④ 보기를 찾아낸다.
  2) 정답 파일(가답안/확정답안)에서 "문항번호 → 정답번호" 표를 읽는다. 정답 파일이 없으면 answer=0 으로 두고 나중에 채운다.
  3) data/bank/{year}_{round}_{subject}.json 으로 저장하고, --build 로 전체를 병합한다.

PDF 레이아웃이 회차마다 달라 파싱이 100% 정확하지 않을 수 있다. 실행 후 출력되는 검수 리포트(문항 수, 보기 4개 미만 문항, 정답 누락)를 확인하고
data/bank/*.json 을 직접 수정하면 된다. 2단 편집 PDF는 --columns 2 옵션으로 좌우 단을 분리해 읽는다.
"""
import argparse
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
BANK_DIR = ROOT / "data" / "bank"
SUBJECTS = ["보험업법", "보험계약법", "손해사정이론"]
SUBJECT_ALIASES = {
    "보험업법": ["보험업법", "업법"],
    "보험계약법": ["보험계약법", "계약법", "상법"],
    "손해사정이론": ["손해사정이론", "사정이론", "이론"],
}
CIRCLED = "①②③④⑤"
CIRCLED_MAP = {c: i + 1 for i, c in enumerate(CIRCLED)}


# ---------- 텍스트 추출 ----------
def extract_text(path: Path, columns: int = 1) -> str:
    if path.suffix.lower() == ".txt":
        return path.read_text(encoding="utf-8", errors="ignore")
    if path.suffix.lower() != ".pdf":
        sys.exit(f"지원하지 않는 형식: {path.name} (PDF/TXT만 가능. HWP는 한컴오피스에서 PDF로 저장 후 사용)")
    try:
        import pymupdf  # type: ignore
    except ImportError:  # pragma: no cover
        import fitz as pymupdf  # type: ignore
    doc = pymupdf.open(path)
    parts = []
    for page in doc:
        if columns == 2:
            w = page.rect.width
            left = page.get_text("text", clip=pymupdf.Rect(0, 0, w / 2, page.rect.height), sort=True)
            right = page.get_text("text", clip=pymupdf.Rect(w / 2, 0, w, page.rect.height), sort=True)
            parts.append(left + "\n" + right)
        else:
            parts.append(page.get_text("text", sort=True))
    return "\n".join(parts)


def normalize(text: str) -> str:
    text = text.replace(" ", " ").replace("\r", "")
    # 머리글/바닥글 잡음 제거
    text = re.sub(r"^\s*-\s*\d+\s*-\s*$", "", text, flags=re.M)
    text = re.sub(r"^\s*\d+\s*/\s*\d+\s*$", "", text, flags=re.M)
    # 보기 기호 앞에 줄바꿈 보장
    text = re.sub(r"\s*([①②③④⑤])\s*", r"\n\1 ", text)
    return text


# ---------- 문제 파싱 ----------
Q_START = re.compile(r"^\s*(\d{1,3})\s*[.．]\s*(?=\S)", re.M)


def parse_questions(text: str):
    text = normalize(text)
    starts = [(m.start(), int(m.group(1)), m.end()) for m in Q_START.finditer(text)]
    # 문항 번호가 순차적으로 증가하는 것만 채택(본문 내 "1." 같은 잡음 제거)
    seq, expect = [], 1
    for pos, num, end in starts:
        if num == expect:
            seq.append((pos, num, end)); expect += 1
        elif num == expect - 1 and seq:  # 중복 매칭은 무시
            continue
    questions = []
    for i, (pos, num, end) in enumerate(seq):
        block = text[end: seq[i + 1][0] if i + 1 < len(seq) else len(text)]
        lines = [ln.rstrip() for ln in block.split("\n")]
        stem, choices, cur = [], [], None
        for ln in lines:
            s = ln.strip()
            if not s:
                continue
            if s[0] in CIRCLED_MAP:
                cur = CIRCLED_MAP[s[0]]
                while len(choices) < cur:
                    choices.append("")
                choices[cur - 1] = s[1:].strip()
            elif cur is None:
                stem.append(s)
            else:
                choices[cur - 1] = (choices[cur - 1] + " " + s).strip()
        questions.append({
            "num": num,
            "question": "\n".join(stem).strip(),
            "choices": [c.strip() for c in choices[:5]],
        })
    return questions


# ---------- 정답 파싱 ----------
def parse_answers(text: str, subject: str | None = None) -> dict[int, int]:
    """'1 ③ 2 ①' 형태, '1. ③', '1-③', 또는 표 형태(번호 줄 + 정답 줄)를 모두 시도한다."""
    text = text.replace(" ", " ")
    if subject:  # 여러 과목이 한 파일에 있을 때 해당 과목 구간만 사용
        idx = [m.start() for m in re.finditer("|".join(map(re.escape, SUBJECT_ALIASES[subject])), text)]
        if idx:
            start = idx[0]
            others = [m.start() for s in SUBJECTS if s != subject for m in re.finditer(re.escape(s), text) if m.start() > start]
            text = text[start: min(others) if others else len(text)]
    answers: dict[int, int] = {}
    for m in re.finditer(r"(\d{1,3})\s*[.．:\-]?\s*([①②③④⑤])", text):
        n, a = int(m.group(1)), CIRCLED_MAP[m.group(2)]
        if 1 <= n <= 200 and n not in answers:
            answers[n] = a
    if len(answers) < 10:  # 표 형태: 숫자 줄과 기호 줄이 번갈아 나오는 경우
        nums = [int(x) for x in re.findall(r"\b(\d{1,3})\b", text)]
        syms = [CIRCLED_MAP[c] for c in re.findall(r"[①②③④⑤]", text)]
        if len(syms) >= 10 and len(nums) >= len(syms):
            answers = {i + 1: syms[i] for i in range(len(syms))}
    return answers


# ---------- 저장/병합 ----------
def make_id(year, rnd, subject, num):
    return f"{year}-{rnd}-{SUBJECTS.index(subject)}-{num}"


def save_bank(year, rnd, subject, questions, answers, source):
    BANK_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for q in questions:
        out.append({
            "id": make_id(year, rnd, subject, q["num"]),
            "year": year, "round": rnd, "subject": subject, "num": q["num"],
            "question": q["question"], "choices": q["choices"],
            "answer": answers.get(q["num"], 0),
            "explanation": "",
            "source": source,
        })
    path = BANK_DIR / f"{year}_{rnd}_{subject}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    # 검수 리포트
    short = [q["num"] for q in out if len([c for c in q["choices"] if c]) < 4]
    noans = [q["num"] for q in out if not q["answer"]]
    print(f"[저장] {path.relative_to(ROOT)}  문항 {len(out)}개")
    if short:
        print(f"  ! 보기 4개 미만: {short}")
    if noans:
        print(f"  ! 정답 누락: {noans if len(noans) < 20 else str(len(noans)) + '개'}")
    return path


def build():
    files = sorted(BANK_DIR.glob("*.json")) if BANK_DIR.exists() else []
    seed = ROOT / "data" / "seed_questions.json"
    bank, seen = [], set()
    for f in ([seed] if seed.exists() else []) + files:
        for q in json.loads(f.read_text(encoding="utf-8")):
            if not q.get("answer") or len([c for c in q.get("choices", []) if c]) < 2:
                continue  # 정답 없는 문항은 제외
            if q["id"] in seen:
                continue
            seen.add(q["id"]); bank.append(q)
    # 수동 보정: data/overrides.json 의 항목을 id 기준으로 덮어쓴다 (question/choices/answer/accept/explanation)
    ov_path = ROOT / "data" / "overrides.json"
    if ov_path.exists():
        overrides = {o["id"]: o for o in json.loads(ov_path.read_text(encoding="utf-8"))}
        by_id = {q["id"]: q for q in bank}
        for qid, o in overrides.items():
            if qid in by_id:
                by_id[qid].update({k: v for k, v in o.items() if k != "id"})
            elif o.get("question") and o.get("choices") and o.get("answer"):
                bank.append(o)
        bank = [q for q in bank if q.get("answer") and len([c for c in q.get("choices", []) if c]) >= 2]
        print(f"[보정] overrides.json {len(overrides)}건 적용")
    (ROOT / "data" / "questions.json").write_text(json.dumps(bank, ensure_ascii=False, indent=1), encoding="utf-8")
    (ROOT / "data" / "questions.js").write_text("window.QUESTION_BANK = " + json.dumps(bank, ensure_ascii=False) + ";\n", encoding="utf-8")
    by = {s: sum(1 for q in bank if q["subject"] == s) for s in SUBJECTS}
    print(f"[빌드] data/questions.js  총 {len(bank)}문항  " + "  ".join(f"{k} {v}" for k, v in by.items()))


def guess_subject(name: str):
    for s, aliases in SUBJECT_ALIASES.items():
        if any(a in name for a in aliases):
            return s
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int)
    ap.add_argument("--round", type=int, dest="rnd")
    ap.add_argument("--subject", choices=SUBJECTS)
    ap.add_argument("--questions", help="문제 PDF/TXT")
    ap.add_argument("--answers", help="정답 PDF/TXT (선택)")
    ap.add_argument("--auto", help="폴더 지정 시 파일명에서 과목을 추정해 일괄 처리 (정답 파일명에 '정답' 또는 '답안' 포함)")
    ap.add_argument("--columns", type=int, default=1, help="2단 편집 PDF면 2")
    ap.add_argument("--build", action="store_true", help="data/bank/*.json 병합 → data/questions.js")
    ap.add_argument("--dump", help="PDF 텍스트만 추출해 저장(디버그용)")
    a = ap.parse_args()

    if a.dump:
        Path(a.dump).write_text(extract_text(Path(a.questions), a.columns), encoding="utf-8")
        print("텍스트 저장:", a.dump); return

    if a.auto:
        if not (a.year and a.rnd):
            sys.exit("--auto 에는 --year 와 --round 가 필요합니다.")
        folder = Path(a.auto)
        files = [p for p in folder.iterdir() if p.suffix.lower() in (".pdf", ".txt")]
        ans_files = [p for p in files if re.search(r"정답|답안", p.name)]
        ans_text = "\n".join(extract_text(p) for p in ans_files)
        for p in files:
            if p in ans_files:
                continue
            subj = guess_subject(p.name)
            if not subj:
                print(f"  - 과목을 알 수 없어 건너뜀: {p.name}"); continue
            qs = parse_questions(extract_text(p, a.columns))
            answers = parse_answers(ans_text, subj) if ans_text else {}
            save_bank(a.year, a.rnd, subj, qs, answers, f"보험개발원 제{a.rnd}회")
        build(); return

    if a.build:
        build(); return

    if not (a.year and a.rnd and a.subject and a.questions):
        ap.print_help(); sys.exit(1)
    qs = parse_questions(extract_text(Path(a.questions), a.columns))
    answers = parse_answers(extract_text(Path(a.answers)), a.subject) if a.answers else {}
    save_bank(a.year, a.rnd, a.subject, qs, answers, f"보험개발원 제{a.rnd}회")
    build()


if __name__ == "__main__":
    main()
