#!/usr/bin/env python3
"""
띄어쓰기 보정.
import_kidi.join_wrap 이 PDF/HWP 줄바꿈 자리(한글-한글)에 남겨 둔 표식(U+2063)을, 한국어 형태소 분석기(Kiwi)로
"여기서 띄어야 하는가"를 판단해 공백 또는 빈 문자열로 바꾼다. 보험 용어 복합어는 사용자 사전으로 등록해 과도한 분리를 막는다.
또한 공백 없이 10음절 이상 이어진 한글 덩어리(HWP 원문에서 띄어쓰기가 빠진 경우)는 그 구간만 자동 띄어쓰기한다.

  python tools/respace.py            # data/bank/*.json 전체 보정 후 questions.js 재생성
  python tools/respace.py --test     # 예문으로 동작 확인
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_pdf import build, BANK_DIR  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SEP = "⁣"
HANGUL_RUN = re.compile(r"[가-힣]{8,}")

TERMS = """
보험계약 보험계약자 보험수익자 피보험자 피보험이익 보험가액 보험금액 보험약관 보험증권 보험기간 보험사고 보험목적 보험목적물
손해보험 생명보험 상해보험 질병보험 화재보험 해상보험 운송보험 책임보험 자동차보험 보증보험 재보험 인보험 단체보험 소급보험
중복보험 초과보험 일부보험 전부보험 기평가보험 미평가보험 신가보험 병존보험 타인을위한보험
보험회사 보험자 보험료 보험금 보험금청구권 보험료청구권 보험업 보험업법 보험상품 보험종목 보험대리점 보험중개사 보험설계사 보험모집
보험계리사 보험계리업 선임계리사 보험협회 보험개발원 보험요율 보험요율산출기관 금융위원회 금융감독원 금융감독원장 금융기관보험대리점
손해사정 손해사정사 손해사정업 손해사정업자 손해사정서 손해액 손해방지 손해방지비용 손해배상 손해배상책임 손해배상청구권
고지의무 통지의무 위험변경 위험증가 낙부통지 승낙의제 약관교부 설명의무 청약철회 계약해지 계약해제 계약부활 해지환급금
청구권대위 잔존물대위 보험자대위 대위권 소멸시효 불이익변경금지 면책사유 면책조항 담보위험 면책위험 직접청구권 방어비용
자본금 기금 상호회사 주식회사 외국보험회사 국내지점 조직변경 자본감소 사원총회 손실보전준비금 책임준비금 비상위험준비금 지급여력비율
특별계정 일반계정 자산운용 신용공여 대주주 자회사 겸영업무 부수업무 기초서류 사업방법서 산출방법서 계약이전 허가취소 등록취소 업무정지
보험안내자료 특별이익 승환계약 자기계약 통신판매 통신판매전문보험회사 소액단기전문보험회사 전문보험계약자 일반보험계약자
비례보상 실손보상 이득금지 근인주의 최대선의 위험관리 위험보유 위험전가 위험회피 손실통제 대수의법칙 역선택 도덕적위험 도덕적위태
실제현금가치 재조달가액 감가상각 잔존물 잔존물제거비용 공동보험 공동해손 단독해손 추정전손 현실전손 보험위부 감항능력 항해변경
언더라이팅 경험요율 소급요율 예정요율 순보험료 부가보험료 손해율 합산비율 임의재보험 특약재보험 비례재보험 초과손해액재보험
대인배상 대물배상 자기신체사고 자기차량손해 무보험자동차 과실상계 손익상계 일실수입 상실수익액 위자료 휴업손해 노동능력상실률
피해자 가해자 제3자 사용자 임차인 수익자 상속인 대리인 대리상 청약자 채권자 채무자 주채무자 보증인
상법 민법 시행령 시행규칙 판례 대법원 금융소비자보호법 자동차손해배상보장법 약관규제법 근로자퇴직급여보장법
"""


def make_kiwi():
    from kiwipiepy import Kiwi
    kiwi = Kiwi()
    for w in TERMS.split():
        kiwi.add_user_word(w, "NNG", 5.0)
    return kiwi


class Respacer:
    def __init__(self):
        self.kiwi = make_kiwi()
        self.cache = {}

    def space_at(self, left: str, right: str) -> bool:
        """left|right 경계에 공백이 들어가야 하면 True"""
        key = (left, right)
        if key in self.cache:
            return self.cache[key]
        s = left + right
        out = self.kiwi.space(s, reset_whitespace=False)
        need = len(left.replace(" ", ""))
        n, ans = 0, False
        for i, ch in enumerate(out):
            if not ch.isspace():
                n += 1
            if n == need:
                ans = i + 1 < len(out) and out[i + 1] == " "
                break
        self.cache[key] = ans
        return ans

    def resolve(self, text: str) -> str:
        if not text:
            return text
        while SEP in text:
            i = text.index(SEP)
            left = text[:i].replace(SEP, "")[-14:]
            right = text[i + 1:].replace(SEP, "")[:14]
            text = text[:i] + (" " if self.space_at(left, right) else "") + text[i + 1:]
        # 공백 없이 길게 이어진 한글 덩어리(원문 띄어쓰기 누락)
        def fix_run(m):
            return self.kiwi.space(m.group(0), reset_whitespace=False)
        text = HANGUL_RUN.sub(fix_run, text)
        return re.sub(r" {2,}", " ", text).strip()


def respace_bank():
    rs = Respacer()
    files = sorted(BANK_DIR.glob("*.json"))
    changed_total = 0
    for f in files:
        qs = json.loads(f.read_text(encoding="utf-8"))
        changed = 0
        for q in qs:
            nq = rs.resolve(q["question"])
            nc = [rs.resolve(c) for c in q["choices"]]
            if nq != q["question"] or nc != q["choices"]:
                changed += 1
            q["question"], q["choices"] = nq, nc
        f.write_text(json.dumps(qs, ensure_ascii=False, indent=1), encoding="utf-8")
        changed_total += changed
        print(f"[보정] {f.name}: {changed}/{len(qs)}문항 수정")
    print(f"총 {changed_total}문항 수정")
    build()


def self_test():
    rs = Respacer()
    tests = [
        "우발적인" + SEP + "사고로서 보험약관상 보험자의",
        "보험금을 지급할" + SEP + "책임을 면하지 못한다",
        "보험계약을 해지할" + SEP + "수 있다",
        "퇴직보" + SEP + "험계약의 경우 특별계정을",
        "보험" + SEP + "계약자 또는 피보험자나",
        "회계처리하" + SEP + "여야 한다",
        "보험사고가 발생한 후에는" + SEP + "보험계약을 해지할 수 없다",
        "다음보험가능리스크(insurablerisk)의요건중피보험이익의 원칙과 가장 관련이 깊은 것은?",
        "손해보험계약 체결시 당사자간에 보험가액을 정한 때에는",
    ]
    for t in tests:
        print(repr(t.replace(SEP, "|")), "->", repr(rs.resolve(t)))


if __name__ == "__main__":
    if "--test" in sys.argv:
        self_test()
    else:
        respace_bank()
