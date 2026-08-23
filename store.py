# -*- coding: utf-8 -*-
"""SQLite 저장소 + 조건 매칭(스코어링) 엔진"""
import os, re, json, sqlite3, hashlib, datetime, pathlib

BASE = pathlib.Path(__file__).resolve().parent
DB_PATH = BASE / "data" / "notices.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

SCHEMA = """
CREATE TABLE IF NOT EXISTS notices (
  uid        TEXT PRIMARY KEY,
  agency     TEXT, menu TEXT, category TEXT,
  title      TEXT, url TEXT,
  region_hint TEXT, sido TEXT, sigungu TEXT,
  deal       TEXT, house_type TEXT, quals TEXT, kind TEXT,
  posted     TEXT, deadline TEXT, status TEXT,
  first_seen TEXT, last_seen TEXT
);
CREATE INDEX IF NOT EXISTS ix_notices_posted ON notices(posted);
CREATE INDEX IF NOT EXISTS ix_notices_agency ON notices(agency);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started TEXT, finished TEXT,
  total INTEGER, new INTEGER, errors TEXT
);

CREATE TABLE IF NOT EXISTS prefs (
  name TEXT PRIMARY KEY, payload TEXT, updated TEXT
);
"""

# ── 사장님 기본 조건 (2026-08-23 지시 기준) ───────────────────────────
DEFAULT_PREF = {
    "name": "우리 조건",
    "note": "예비 신혼부부(혼인신고 예정 2026-11-07) / 현 거주 경기 구리",
    "regions": [
        {"sido": "경기", "sigungu": "구리"},
        {"sido": "경기", "sigungu": "남양주"},
        {"sido": "경기", "sigungu": "의정부"},
        {"sido": "서울", "sigungu": "중랑"},
        {"sido": "서울", "sigungu": "광진"},
        {"sido": "서울", "sigungu": "동대문"},
        {"sido": "서울", "sigungu": "노원"},
    ],
    "deals": ["임대(전세)", "임대(월세)", "매매(분양·매각)"],
    "quals": ["신혼·신생아", "청년", "일반"],
    "kinds": ["모집공고"],
    "exclude_kinds": ["결과발표"],
    "open_only": True,
    "birth": {"male": "1988-12", "female": "1992-02"},
    "wedding": "2026-11-07",
}


def conn():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init():
    c = conn()
    c.executescript(SCHEMA)
    cur = c.execute("SELECT COUNT(*) n FROM prefs WHERE name=?", (DEFAULT_PREF["name"],))
    if cur.fetchone()["n"] == 0:
        c.execute("INSERT INTO prefs(name,payload,updated) VALUES(?,?,?)",
                  (DEFAULT_PREF["name"], json.dumps(DEFAULT_PREF, ensure_ascii=False),
                   datetime.datetime.now().isoformat(timespec="seconds")))
    c.commit()
    c.close()


def make_uid(r):
    key = "%s|%s|%s" % (r.get("agency", ""), r.get("title", ""), r.get("posted", ""))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def upsert(rows):
    """수집 결과 저장. (총건수, 신규건수) 반환"""
    import classify
    now = datetime.datetime.now().isoformat(timespec="seconds")
    c = conn()
    new = 0
    for r in rows:
        uid = make_uid(r)
        sido, gu = classify.detect_region(r.get("title", ""), r.get("region_hint", ""), r.get("agency", ""))
        rec = (
            uid, r.get("agency"), r.get("menu"), r.get("category"),
            r.get("title"), r.get("url"), r.get("region_hint"), sido, gu,
            classify.detect_deal(r.get("title", ""), r.get("category", "")),
            classify.detect_house_type(r.get("title", ""), r.get("category", "")),
            json.dumps(classify.detect_quals(r.get("title", "")), ensure_ascii=False),
            classify.detect_kind(r.get("title", ""), r.get("category", "")),
            r.get("posted"), r.get("deadline"), r.get("status"),
        )
        ex = c.execute("SELECT uid FROM notices WHERE uid=?", (uid,)).fetchone()
        if ex is None:
            c.execute("""INSERT INTO notices
                (uid,agency,menu,category,title,url,region_hint,sido,sigungu,
                 deal,house_type,quals,kind,posted,deadline,status,first_seen,last_seen)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rec + (now, now))
            new += 1
        else:
            c.execute("""UPDATE notices SET agency=?,menu=?,category=?,title=?,url=?,
                region_hint=?,sido=?,sigungu=?,deal=?,house_type=?,quals=?,kind=?,
                posted=?,deadline=?,status=?,last_seen=? WHERE uid=?""",
                      rec[1:] + (now, uid))
    c.commit()
    c.close()
    return len(rows), new


def log_run(started, total, new, errors):
    c = conn()
    c.execute("INSERT INTO runs(started,finished,total,new,errors) VALUES(?,?,?,?,?)",
              (started, datetime.datetime.now().isoformat(timespec="seconds"),
               total, new, json.dumps(errors, ensure_ascii=False)))
    c.commit()
    c.close()


def last_run():
    c = conn()
    r = c.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    c.close()
    return dict(r) if r else None


# ── 조건 매칭 ────────────────────────────────────────────────────────
def dday(deadline):
    if not deadline:
        return None
    try:
        d = datetime.date.fromisoformat(deadline)
    except Exception:
        return None
    return (d - datetime.date.today()).days


def match_score(row, pref):
    """0~100 적합도 + 매칭 사유"""
    score, why = 0, []
    regions = pref.get("regions") or []
    sido, gu = row["sido"] or "", row["sigungu"] or ""

    # 1) 지역 (최대 45). 희망 시군구를 지정했으면 같은 시도의 '다른 시군구'는 감점한다.
    if regions:
        want_gu = [r["sigungu"] for r in regions if r.get("sigungu")]
        exact = any(g and g in gu for g in want_gu)
        sido_ok = any(r.get("sido") == sido for r in regions)
        if exact:
            score += 45; why.append("희망 시군구 일치(%s %s)" % (sido, gu))
        elif sido_ok and not gu:
            # 시도만 맞고 시군구 미상 -> 확인 가치 있음
            score += 22; why.append("희망 시도 일치·시군구 미상(%s)" % sido)
        elif sido_ok and gu:
            score += 6; why.append("희망 시도지만 타 시군구(%s %s)" % (sido, gu))
        elif sido in ("전국", ""):
            score += 8; why.append("전국/지역미상")
        else:
            score -= 20; why.append("희망지역 밖(%s %s)" % (sido, gu))
    else:
        score += 20

    # 2) 거래유형 (최대 20). 지정한 유형 밖이면 사실상 배제.
    deals = pref.get("deals") or []
    if not deals or row["deal"] in deals:
        score += 20; why.append("거래유형 %s" % row["deal"])
    else:
        score -= 40; why.append("※거래유형 제외대상(%s)" % row["deal"])

    # 3) 자격 (최대 20)
    try:
        rq = json.loads(row["quals"] or "[]")
    except Exception:
        rq = []
    want = pref.get("quals") or []
    hit = [q for q in rq if q in want]
    if hit:
        score += 20 if any(h != "일반" for h in hit) else 10
        why.append("자격 " + "/".join(hit))

    # 4) 공고 성격 (최대 10) — 결과발표는 감점
    if row["kind"] in (pref.get("exclude_kinds") or []):
        score -= 25; why.append("※" + row["kind"])
    elif row["kind"] in (pref.get("kinds") or ["모집공고"]):
        score += 10; why.append(row["kind"])

    # 5) 마감 임박/유효 (최대 15)
    dd = dday(row["deadline"])
    if dd is not None:
        if dd < 0:
            score -= 30; why.append("마감(%d일 경과)" % abs(dd))
        elif dd <= 7:
            score += 15; why.append("D-%d 마감임박" % dd)
        else:
            score += 8; why.append("D-%d" % dd)
    elif (row["status"] or "") in ("공고중", "접수중"):
        score += 10; why.append("공고중")

    return max(0, min(100, score)), why


def query(pref=None, filters=None, limit=500):
    """필터 적용 + 스코어 정렬된 목록"""
    filters = filters or {}
    c = conn()
    sql = "SELECT * FROM notices WHERE 1=1"
    args = []
    if filters.get("agency"):
        ags = filters["agency"]
        sql += " AND agency IN (%s)" % ",".join("?" * len(ags)); args += ags
    if filters.get("deal"):
        ds = filters["deal"]
        sql += " AND deal IN (%s)" % ",".join("?" * len(ds)); args += ds
    if filters.get("sido"):
        ss = filters["sido"]
        sql += " AND sido IN (%s)" % ",".join("?" * len(ss)); args += ss
    if filters.get("q"):
        sql += " AND title LIKE ?"; args.append("%" + filters["q"] + "%")
    if filters.get("hide_results"):
        sql += " AND kind <> '결과발표'"
    if filters.get("since"):
        sql += " AND posted >= ?"; args.append(filters["since"])
    if filters.get("days"):
        cut = (datetime.date.today() - datetime.timedelta(days=int(filters["days"]))).isoformat()
        sql += " AND posted >= ?"; args.append(cut)
    sql += " ORDER BY posted DESC LIMIT 2000"
    rows = c.execute(sql, args).fetchall()
    c.close()

    out = []
    for r in rows:
        d = dict(r)
        try:
            d["quals"] = json.loads(d["quals"] or "[]")
        except Exception:
            d["quals"] = []
        d["dday"] = dday(d["deadline"])
        if pref:
            d["score"], d["why"] = match_score(r, pref)
        else:
            d["score"], d["why"] = 0, []
        # 마감 지난 건 숨김 옵션
        if filters.get("open_only") and d["dday"] is not None and d["dday"] < 0:
            continue
        if filters.get("min_score") and d["score"] < int(filters["min_score"]):
            continue
        out.append(d)
    out.sort(key=lambda x: (-x["score"], x["posted"] or ""), reverse=False)
    out.sort(key=lambda x: (-x["score"], -(0 if not x["posted"] else int(x["posted"].replace("-", "")))))
    return out[:limit]


def get_pref(name="우리 조건"):
    c = conn()
    r = c.execute("SELECT payload FROM prefs WHERE name=?", (name,)).fetchone()
    c.close()
    return json.loads(r["payload"]) if r else dict(DEFAULT_PREF)


def save_pref(pref):
    c = conn()
    c.execute("INSERT INTO prefs(name,payload,updated) VALUES(?,?,?) "
              "ON CONFLICT(name) DO UPDATE SET payload=excluded.payload, updated=excluded.updated",
              (pref["name"], json.dumps(pref, ensure_ascii=False),
               datetime.datetime.now().isoformat(timespec="seconds")))
    c.commit()
    c.close()


def list_prefs():
    c = conn()
    rows = [r["name"] for r in c.execute("SELECT name FROM prefs ORDER BY name").fetchall()]
    c.close()
    return rows


def stats():
    c = conn()
    s = {}
    s["total"] = c.execute("SELECT COUNT(*) n FROM notices").fetchone()["n"]
    s["by_agency"] = {r["agency"]: r["n"] for r in
                      c.execute("SELECT agency,COUNT(*) n FROM notices GROUP BY agency")}
    s["by_deal"] = {r["deal"]: r["n"] for r in
                    c.execute("SELECT deal,COUNT(*) n FROM notices GROUP BY deal ORDER BY n DESC")}
    c.close()
    return s


if __name__ == "__main__":
    init()
    print("DB 준비:", DB_PATH)
