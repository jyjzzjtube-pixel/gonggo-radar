# -*- coding: utf-8 -*-
"""LH 공식 OpenAPI 수집기 (공공데이터포털, 무료)

웹 파싱(collectors.collect_lh)의 대체·보강용이다.
apply.lh.or.kr은 GitHub Actions runner IP에서 간헐적으로 connect timeout이 나는데,
apis.data.go.kr은 별도 인프라라 그 영향을 받지 않는다.

키는 환경변수 DATA_GO_KR_KEY 로 주입한다.
  - 로컬: ~/.claude/.env
  - CI  : GitHub Secrets (repo secret) -> workflow env
키가 없으면 조용히 빈 결과를 돌려주고, 호출한 쪽이 웹 파싱으로 폴백한다.
"""
import os
import json
import time
import urllib.parse
import urllib.request

BASE = "https://apis.data.go.kr/B552555"
NOTICE = BASE + "/lhLeaseNoticeInfo1/lhLeaseNoticeInfo1"

# 공고 유형 코드 (UPP_AIS_TP_CD)
UPP_TYPES = [
    ("05", "임대주택"),
    ("06", "분양주택"),
    ("07", "토지"),
    ("08", "상가"),
]


def _key():
    k = os.environ.get("DATA_GO_KR_KEY", "").strip()
    if k:
        return k
    # 로컬 실행 편의: ~/.claude/.env 에서 읽는다
    env = os.path.join(os.path.expanduser("~"), ".claude", ".env")
    if os.path.exists(env):
        try:
            with open(env, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("DATA_GO_KR_KEY="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
    return ""


def _get(params, timeout=30):
    url = NOTICE + "?" + urllib.parse.urlencode(params, safe="%")
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
    return raw


def _rows(raw):
    """응답에서 레코드 배열을 뽑는다. LH API는 [{헤더},{ dsList:[...] }] 형태로 온다."""
    try:
        d = json.loads(raw)
    except Exception:
        return [], "JSON 아님(키 오류/한도초과 가능): " + raw[:120]
    if isinstance(d, dict):
        # 에러 응답
        if "OpenAPI_ServiceResponse" in d:
            hdr = d["OpenAPI_ServiceResponse"].get("cmmMsgHeader", {})
            return [], "%s / %s" % (hdr.get("returnAuthMsg"), hdr.get("errMsg"))
        d = [d]
    out = []
    for part in d if isinstance(d, list) else []:
        if not isinstance(part, dict):
            continue
        for k, v in part.items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                out.extend(v)
    return out, None


def _date(s):
    s = (s or "").strip()
    if len(s) == 8 and s.isdigit():
        return "%s-%s-%s" % (s[:4], s[4:6], s[6:8])
    return s.replace(".", "-")[:10] if s else ""


def collect(pages=2, page_size=100, log=print):
    """LH 공고를 collectors 와 동일한 dict 스키마로 돌려준다."""
    key = _key()
    if not key:
        log("  [LH API] DATA_GO_KR_KEY 없음 -> 건너뜀(웹 파싱으로 대체)")
        return []
    out, errs = [], []
    for code, name in UPP_TYPES:
        for pg in range(1, pages + 1):
            params = {
                "serviceKey": key,
                "PG_SN": pg,
                "PAGE_SIZE": page_size,
                "UPP_AIS_TP_CD": code,
            }
            try:
                raw = _get(params)
            except Exception as e:
                log("  [LH API %s p%d] ERR %s" % (name, pg, e))
                errs.append(str(e))
                break
            rows, err = _rows(raw)
            if err:
                log("  [LH API %s] %s" % (name, err))
                errs.append(err)
                break
            if not rows:
                break
            for r in rows:
                title = (r.get("PAN_NM") or r.get("panNm") or "").strip()
                if not title:
                    continue
                out.append(dict(
                    agency="LH",
                    menu=name,
                    category=(r.get("AIS_TP_CD_NM") or r.get("SPL_INF_TP_NM") or name),
                    title=title,
                    region_hint=(r.get("CNP_CD_NM") or r.get("ALL_CNP_CD_NM") or ""),
                    posted=_date(r.get("PAN_NT_ST_DT") or r.get("PAN_DT")),
                    deadline=_date(r.get("CLSG_DT") or r.get("PAN_ED_DT")),
                    status=(r.get("PAN_SS") or r.get("PAN_SS_NM") or ""),
                    url=(r.get("DTL_URL") or r.get("PAN_DTL_URL")
                         or "https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancList.do?mi=1026"),
                ))
            log("  [LH API %s p%d] %d건" % (name, pg, len(rows)))
            if len(rows) < page_size:
                break
            time.sleep(0.3)
    if errs and not out:
        log("  [LH API] 전부 실패 -> 웹 파싱으로 대체")
    return out


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    rs = collect(pages=1, log=print)
    print("총", len(rs), "건")
    for r in rs[:3]:
        print(json.dumps(r, ensure_ascii=False)[:200])
