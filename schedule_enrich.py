# -*- coding: utf-8 -*-
"""공고 상세에서 청약 일정을 뽑아 채운다.

목록 페이지에는 마감일 정도만 있어서 "언제부터 넣을 수 있는지"를 알 수 없다.
청약은 접수 시작일을 미리 알아야 준비가 되므로, 진행 가능성이 있는 건만
상세를 열어 아래 일정을 채운다.

  rs / re : 접수 시작 / 종료
  dr      : 서류제출대상자(서류심사대상자) 발표일
  ds / de : 서류 제출 시작 / 종료
  wr      : 당첨자 발표일

3사 모두 표기가 달라 키워드 사전 + 날짜 정규식으로 처리한다.
LH·GH는 "접수기간 : 2026.08.24 ~ 2026.08.26" 같은 정형,
SH는 "2026. 9. 1(화) ~ 2026. 9. 3.(목)" 같은 본문 서술형이다.
"""
import re
import sys
import time
import datetime
from concurrent.futures import ThreadPoolExecutor

import collectors as C
from bs4 import BeautifulSoup

# 2026. 9. 1  /  2026.08.24  /  2026-08-24 를 모두 잡는다
DATE = r"(20\d{2})\s*[.\-]\s*(\d{1,2})\s*[.\-]\s*(\d{1,2})"
# "2026.08.24 10:00 ~ 2026.08.26 18:00" 처럼 사이에 시각이 끼어도 잡히도록
# ~ 앞뒤를 숫자 배제가 아니라 최소 매칭으로 둔다.
RANGE = DATE + r".{0,28}?~.{0,28}?" + DATE

FIELDS = [
    # (결과키, 범위여부, 키워드들)
    ("rs", True,  ["온라인접수기간", "인터넷접수기간", "접수기간", "청약접수기간",
                   "신청기간", "청약기간", "접수일정", "모집기간"]),
    ("dr", False, ["서류제출대상자 발표", "서류심사대상자 발표", "서류제출대상자발표",
                   "서류심사대상자발표", "서류제출대상자 발표일"]),
    ("ds", True,  ["서류접수기간", "서류제출기간", "심사서류제출기간"]),
    ("wr", False, ["당첨자발표일", "당첨자 발표일", "당첨자발표", "당첨자 발표"]),
]


def _norm(y, m, d):
    try:
        return "%04d-%02d-%02d" % (int(y), int(m), int(d))
    except Exception:
        return ""


def parse_schedule(text):
    """상세 본문 텍스트에서 일정을 뽑는다."""
    t = re.sub(r"\s+", " ", text or "")
    out = {}
    for key, is_range, kws in FIELDS:
        for kw in kws:
            i = t.find(kw)
            if i < 0:
                continue
            seg = t[i:i + 170]          # 키워드 뒤 짧은 구간에서만 찾는다
            if is_range:
                endkey = "re" if key == "rs" else "de"
                m = re.search(RANGE, seg)
                if m:
                    g = m.groups()
                    a, b = _norm(g[0], g[1], g[2]), _norm(g[3], g[4], g[5])
                    if a and b and a <= b:      # 시작이 종료보다 뒤면 오인식
                        out[key], out[endkey] = a, b
                        break
                m = re.search(DATE, seg)
                if m:
                    out[key] = _norm(*m.groups())
                    break
            else:
                m = re.search(DATE, seg)
                if m:
                    out[key] = _norm(*m.groups())
                    break
    return out


# ── 기관별 상세 본문 취득 ────────────────────────────────────────────
def _text_lh(sess, url):
    r = sess.get(url, timeout=30)
    return BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)


def _text_sh(sess, url):
    r = sess.get(url, timeout=30)
    so = BeautifulSoup(r.text, "html.parser")
    for sel in (".bbs_view", ".board_view", ".view_cont", "#contents"):
        el = so.select_one(sel)
        if el:
            return el.get_text(" ", strip=True)
    return so.get_text(" ", strip=True)


def _text_gh_apply(sess, url):
    r = sess.get(url, timeout=35)
    r.encoding = r.apparent_encoding or "utf-8"
    return BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)


def _text_gh(sess, url):
    r = sess.get(url, timeout=30)
    r.encoding = r.apparent_encoding or "utf-8"
    return BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)


def _pick(item):
    """항목에 맞는 (세션종류, 취득함수)를 고른다."""
    u = item.get("url") or ""
    if "apply.lh.or.kr" in u:
        return "plain", _text_lh
    if "i-sh.co.kr" in u:
        return "plain", _text_sh
    if "apply.gh.or.kr" in u:
        return "legacy", _text_gh_apply
    if "gh.or.kr" in u:
        return "plain", _text_gh
    return None, None


def _worth(item, today, days=120):
    """상세를 열어볼 가치가 있는가 — 끝난 공고는 건너뛴다."""
    if not (item.get("url") or "").startswith("http"):
        return False
    dl = item.get("deadline") or ""
    if dl:
        try:
            if datetime.date.fromisoformat(dl) < today:
                return False       # 이미 마감
        except Exception:
            pass
    p = item.get("posted") or ""
    if p:
        try:
            if (today - datetime.date.fromisoformat(p)).days > days:
                return False       # 너무 오래된 공고
        except Exception:
            pass
    return True


def enrich(items, max_items=200, workers=6, log=print):
    """진행 가능성이 있는 항목의 상세를 열어 일정을 채운다. (채운 건수, 실패수)"""
    today = datetime.date.today()
    cand = [it for it in items if _worth(it, today)]

    # 자를 때 뒤쪽 기관이 통째로 빠지지 않도록 급한 것부터 정렬한다.
    # (실제로 GH 청약센터가 목록 끝이라 220건 제한에 잘려 다산 일정이 비었다)
    def prio(it):
        st = (it.get("status") or "")
        live = 0 if any(k in st for k in ("공고중", "접수중", "접수예정")) else 1
        dl = it.get("deadline") or "9999-99-99"
        return (live, dl, it.get("agency", ""))
    cand.sort(key=prio)
    targets = cand[:max_items]
    log("  [일정] 대상 %d건 / 전체 %d건" % (len(targets), len(items)))
    if not targets:
        return 0, 0

    sess = {"plain": C._session(), "legacy": C._session(legacy_tls=True)}
    sess["legacy"].headers["Referer"] = "https://apply.gh.or.kr/co/coa/selectMainView.do"

    filled = [0]
    failed = [0]

    def work(it):
        kind, fn = _pick(it)
        if not fn:
            return
        try:
            txt = fn(sess[kind], it["url"])
            sch = parse_schedule(txt)
            if sch:
                it.update({k: v for k, v in sch.items() if v})
                filled[0] += 1
        except Exception:
            failed[0] += 1

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(work, targets))

    log("  [일정] 채움 %d건 / 실패 %d건" % (filled[0], failed[0]))
    return filled[0], failed[0]


if __name__ == "__main__":
    import io, json
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    # 정답지: 다산진건데시앙 (공고문 PDF 실측값)
    truth = {"rs": "2026-08-24", "re": "2026-08-26", "dr": "2026-09-17",
             "ds": "2026-09-21", "de": "2026-09-28", "wr": "2027-03-04"}
    item = {"agency": "GH",
            "url": "https://apply.gh.or.kr/sb/sr/sr7150/selectPbancDetailView.do?pbancNo=808&pbancKndCd=01",
            "deadline": "2026-08-26", "posted": "2026-08-13"}
    enrich([item], log=print)
    print("추출:", json.dumps({k: item.get(k) for k in truth}, ensure_ascii=False))
    print("정답:", json.dumps(truth, ensure_ascii=False))
    ok = sum(1 for k, v in truth.items() if item.get(k) == v)
    print("일치: %d/%d" % (ok, len(truth)))
