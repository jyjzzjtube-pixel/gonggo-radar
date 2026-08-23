# -*- coding: utf-8 -*-
"""LH / SH / GH 공고 수집기 - 공개 목록 페이지 HTML 파싱 (무료·비인증)"""
import re, time
import requests
from bs4 import BeautifulSoup

requests.packages.urllib3.disable_warnings()

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def _session(legacy_tls=False):
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
    s.verify = False
    if legacy_tls:
        # apply.gh.or.kr은 구형 TLS라 기본 설정으로는 핸드셰이크가 실패한다.
        import ssl
        from requests.adapters import HTTPAdapter
        from urllib3.util.ssl_ import create_urllib3_context

        class _Legacy(HTTPAdapter):
            def init_poolmanager(self, *a, **kw):
                ctx = create_urllib3_context(ciphers="DEFAULT@SECLEVEL=1")
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                ctx.options |= 0x4          # OP_LEGACY_SERVER_CONNECT
                kw["ssl_context"] = ctx
                return super().init_poolmanager(*a, **kw)
        s.mount("https://", _Legacy())
    return s


def _date(s):
    """2026.08.21 / 26.08.20 / 2026-08-21 -> 2026-08-21"""
    if not s:
        return ""
    m = re.search(r"(\d{2,4})[.\-/](\d{1,2})[.\-/](\d{1,2})", s.strip())
    if not m:
        return ""
    y, mo, d = m.groups()
    y = int(y)
    if y < 100:
        y += 2000
    return "%04d-%02d-%02d" % (y, int(mo), int(d))


def _pick_table(soup, need_cols):
    for t in soup.find_all("table"):
        ths = [x.get_text(strip=True) for x in t.find_all("th")]
        if all(c in ths for c in need_cols):
            return t
    return None


# -------------------------------- LH --------------------------------
LH_BASE = "https://apply.lh.or.kr"
LH_LIST = LH_BASE + "/lhapply/apply/wt/wrtanc/selectWrtancList.do"
LH_MENUS = [("1026", "임대주택"), ("1027", "분양주택"), ("1062", "토지"), ("1069", "상가")]


def collect_lh(pages=2, sleep=0.6, log=print):
    s = _session()
    out = []
    for mi, menu in LH_MENUS:
        for pg in range(1, pages + 1):
            try:
                # listCo 파라미터는 LH 서버가 거부(응답 축소) -> 기본 50건/페이지 사용
                r = s.get(LH_LIST, params={"mi": mi, "currPage": pg}, timeout=30)
            except Exception as e:
                log("  [LH %s p%d] ERR %s" % (menu, pg, e))
                break
            tb = _pick_table(BeautifulSoup(r.text, "html.parser"), ["공고명", "지역"])
            if tb is None:
                break
            got = 0
            for tr in tb.find_all("tr"):
                tds = tr.find_all("td")
                if len(tds) < 8:
                    continue
                a = tr.find("a", href=True)
                # LH 목록 링크는 javascript: 이고 실제 키는 data-id1~4 속성에 있다.
                # panId=data-id1, ccrCnntSysDsCd=data-id2, uppAisTpCd=data-id3, aisTpCd=data-id4
                href = ""
                if a is not None and a.get("data-id1"):
                    href = (LH_BASE + "/lhapply/apply/wt/wrtanc/selectWrtancInfo.do"
                            "?panId=%s&ccrCnntSysDsCd=%s&uppAisTpCd=%s&aisTpCd=%s&mi=%s"
                            % (a.get("data-id1"), a.get("data-id2", ""),
                               a.get("data-id3", ""), a.get("data-id4", ""), mi))
                elif a is not None and a["href"].startswith("/"):
                    href = LH_BASE + a["href"]
                title = re.sub(r"\s*\d+일전\s*$", "", tds[2].get_text(" ", strip=True)).strip()
                out.append(dict(
                    agency="LH", menu=menu,
                    category=tds[1].get_text(strip=True),
                    title=title,
                    region_hint=tds[3].get_text(strip=True),
                    posted=_date(tds[5].get_text(strip=True)),
                    deadline=_date(tds[6].get_text(strip=True)),
                    status=tds[7].get_text(strip=True),
                    url=href or (LH_LIST + "?mi=" + mi),
                ))
                got += 1
            log("  [LH %s p%d] %d건" % (menu, pg, got))
            if got == 0:
                break
            time.sleep(sleep)
    return out


# -------------------------------- SH --------------------------------
SH_BASE = "https://www.i-sh.co.kr"
SH_CATS = [
    ("주택분양", "/main/lay2/program/S1T294C296/www/brd/m_244/list.do", "1"),
    ("주택임대", "/main/lay2/program/S1T294C297/www/brd/m_247/list.do", "2"),
    ("주택매입", "/main/lay2/program/S1T294C3379/www/brd/m_247/list.do", "512"),
    ("토지", "/main/lay2/program/S1T294C299/www/brd/m_255/list.do", "8"),
    ("상가공장", "/main/lay2/program/S1T294C300/www/brd/m_256/list.do", "16"),
]


def collect_sh(pages=3, sleep=0.6, log=print):
    s = _session()
    out = []
    for name, path, seq in SH_CATS:
        for pg in range(1, pages + 1):
            try:
                r = s.get(SH_BASE + path, params={"multi_itm_seq": seq, "page": pg}, timeout=30)
            except Exception as e:
                log("  [SH %s p%d] ERR %s" % (name, pg, e))
                break
            tb = _pick_table(BeautifulSoup(r.text, "html.parser"), ["제목", "등록일"])
            if tb is None:
                break
            got = 0
            for tr in tb.find_all("tr"):
                tds = tr.find_all("td")
                if len(tds) < 4:
                    continue
                a = tr.find("a", href=True)
                # SH 목록 링크는 href="#" 이고 onclick="getDetailView('308968')" 로 이동한다.
                # 실제 상세는 같은 경로의 view.do?seq=<번호>&multi_itm_seq=<분류>
                href = ""
                oc = (a.get("onclick") or "") if a is not None else ""
                m = re.search(r"getDetailView\(\s*['\"](\d+)['\"]", oc)
                if m:
                    href = (SH_BASE + path.rsplit("/", 1)[0] + "/view.do?seq=%s&multi_itm_seq=%s"
                            % (m.group(1), seq))
                elif a is not None and a["href"].startswith("/"):
                    href = SH_BASE + a["href"]
                out.append(dict(
                    agency="SH", menu=name, category=name,
                    title=tds[1].get_text(" ", strip=True),
                    region_hint="서울특별시",
                    posted=_date(tds[3].get_text(strip=True)),
                    deadline="", status="",
                    url=href or (SH_BASE + path),
                ))
                got += 1
            log("  [SH %s p%d] %d건" % (name, pg, got))
            if got == 0:
                break
            time.sleep(sleep)
    return out


# -------------------------------- GH --------------------------------
GH_BASE = "https://www.gh.or.kr"
GH_LIST = GH_BASE + "/gh/announcement-of-salerental001.do"
GH_CATS = [("12", "주택"), ("13", "택지"), ("14", "산업단지"),
           ("15", "주택매입"), ("16", "상가"), ("32", "기타")]


def collect_gh(pages=3, sleep=0.6, log=print):
    s = _session()
    out = []
    for cid, name in GH_CATS:
        for pg in range(pages):
            params = {"srCategoryId": cid, "mode": "list",
                      "articleLimit": 10, "article.offset": pg * 10}
            try:
                r = s.get(GH_LIST, params=params, timeout=30)
            except Exception as e:
                log("  [GH %s p%d] ERR %s" % (name, pg + 1, e))
                break
            tb = _pick_table(BeautifulSoup(r.text, "html.parser"), ["제목", "등록일"])
            if tb is None:
                break
            got = 0
            for tr in tb.find_all("tr"):
                tds = tr.find_all("td")
                if len(tds) < 5:
                    continue
                a = tr.find("a", href=True)
                href = a["href"] if a else ""
                # GH 목록 링크는 "?mode=view&articleNo=..." 형태의 상대 쿼리라 base를 붙여야 한다.
                if href.startswith("?"):
                    href = GH_LIST + href
                elif href.startswith("/"):
                    href = GH_BASE + href
                out.append(dict(
                    agency="GH", menu=name,
                    category=tds[1].get_text(strip=True) or name,
                    title=tds[2].get_text(" ", strip=True),
                    region_hint="경기도",
                    posted=_date(tds[4].get_text(strip=True)),
                    deadline="", status="",
                    url=href or GH_LIST,
                ))
                got += 1
            log("  [GH %s p%d] %d건" % (name, pg + 1, got))
            if got == 0:
                break
            time.sleep(sleep)
    return out


# ------------------------ GH 청약센터 (apply.gh.or.kr) ------------------------
# gh.or.kr(본사 공고게시판)과 별개 시스템이다. 실제 임대주택 청약 공고는 여기에만 있다.
GHA_BASE = "https://apply.gh.or.kr"
GHA_LISTS = [
    ("임대주택", "/sb/sr/sr7150/selectPbancRentHouseList.do"),
    ("매입임대", "/sb/sr/sr7155/selectPbancRentHouseList.do"),
    ("임대상가", "/sb/sr/sr7170/selectPbancRentSopsrtList.do"),
]
_DATE2 = re.compile(r"(\d{4}-\d{2}-\d{2})")


def collect_gh_apply(pages=1, sleep=0.6, log=print):
    s = _session(legacy_tls=True)
    s.headers["Referer"] = GHA_BASE + "/co/coa/selectMainView.do"
    out = []
    for name, path in GHA_LISTS:
        try:
            r = s.get(GHA_BASE + path, timeout=40)
            r.encoding = r.apparent_encoding or "utf-8"
        except Exception as e:
            log("  [GH청약 %s] ERR %s" % (name, e))
            continue
        tb = _pick_table(BeautifulSoup(r.text, "html.parser"), ["공고명", "지역"])
        if tb is None:
            log("  [GH청약 %s] 표 없음" % name)
            continue
        got = 0
        for tr in tb.find_all("tr"):
            tds = tr.find_all("td", recursive=False)
            if len(tds) < 4:
                continue
            title = tds[2].get_text(" ", strip=True)
            if not title:
                continue
            # 4번째 칸에 지역·게시일·마감일·상태가 한 덩어리로 들어온다
            rest = tds[3].get_text(" ", strip=True)
            dates = _DATE2.findall(rest)
            posted = dates[0] if dates else ""
            deadline = dates[1] if len(dates) > 1 else ""
            region = rest.split()[0] if rest.split() else "경기도"
            status = ""
            for k in ("공고중", "접수마감", "접수예정", "접수중"):
                if k in rest:
                    status = k
                    break
            a = tr.find("a")
            href = GHA_BASE + path
            if a is not None and a.get("data-pbancno"):
                href = (GHA_BASE + "/sb/sr/sr7150/selectPbancDetailView.do"
                        "?pbancNo=%s&pbancKndCd=%s"
                        % (a.get("data-pbancno"), a.get("data-pbanckndcd", "01")))
            out.append(dict(
                agency="GH", menu="청약센터·" + name,
                category=tds[1].get_text(strip=True) or name,
                title=title,
                region_hint=region if region.endswith(("시", "군", "구", "도")) else "경기도",
                posted=posted, deadline=deadline, status=status,
                url=href,
            ))
            got += 1
        log("  [GH청약 %s] %d건" % (name, got))
        time.sleep(sleep)
    return out


COLLECTORS = [("LH", collect_lh), ("SH", collect_sh), ("GH", collect_gh),
              ("GH청약센터", collect_gh_apply)]


def collect_all(pages=3, log=print):
    rows, errors = [], []
    for name, fn in COLLECTORS:
        log("[%s] 수집 시작" % name)
        try:
            got = fn(pages=pages, log=log)
            rows += got
            log("[%s] 소계 %d건" % (name, len(got)))
            if not got:
                errors.append("%s: 0건 (구조 변경 의심)" % name)
        except Exception as e:
            msg = "%s 실패: %s: %s" % (name, type(e).__name__, e)
            log("[!] " + msg)
            errors.append(msg)
    return rows, errors


if __name__ == "__main__":
    import sys, io, json
    from collections import Counter
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    rs, errs = collect_all(pages=2)
    print("총 %d건" % len(rs))
    print(Counter(r["agency"] for r in rs))
    print("오류:", errs)
    for r in rs[:2]:
        print(json.dumps(r, ensure_ascii=False)[:230])
