# -*- coding: utf-8 -*-
"""정적 PWA 빌드 - 3사 공고를 수집해 dist/data.json 생성.
GitHub Actions에서 주기 실행되며, 산출물(dist)이 GitHub Pages로 배포된다.
어떤 PC도 켜져 있을 필요가 없다."""
import sys, io, os, json, shutil, datetime, pathlib

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import collectors, classify

DIST = BASE / "dist"
WEB = BASE / "web"


LIVE_URL = "https://jyjzzjtube-pixel.github.io/gonggo-radar/data.json"


def _load_previous(log):
    """직전에 배포된 data.json을 가져온다(로컬 dist 우선, 없으면 라이브)."""
    local = DIST / "data.json"
    if local.exists():
        try:
            d = json.loads(local.read_text(encoding="utf-8"))
            if d.get("items"):
                log("    직전 데이터: 로컬 dist (%s)" % d.get("built", ""))
                return d
        except Exception as e:
            log("    로컬 dist 읽기 실패: %s" % e)
    try:
        import urllib.request
        with urllib.request.urlopen(LIVE_URL + "?t=build", timeout=30) as r:
            d = json.loads(r.read().decode("utf-8"))
        log("    직전 데이터: 라이브 (%s)" % d.get("built", ""))
        return d
    except Exception as e:
        log("    라이브 읽기 실패: %s" % e)
    return None


def build(pages=3):
    lines = []

    def log(m):
        print(m)
        lines.append(str(m))

    rows, errors = collectors.collect_all(pages=pages, log=log)

    # ── 차단된 기관 데이터 보존 ─────────────────────────────────────────
    # LH(apply.lh.or.kr)는 GitHub Actions runner IP를 차단한다(connect timeout).
    # 그 기관이 0건이면 마지막으로 배포된 data.json에서 항목을 되살려
    # 데이터가 통째로 사라지는 것을 막고, 낡았다는 사실을 payload에 남긴다.
    stale = {}
    got_agencies = {r["agency"] for r in rows}
    missing = [a for a in ("LH", "SH", "GH") if a not in got_agencies]
    if missing:
        log("[!] 수집 실패 기관: %s -> 직전 배포분에서 복원 시도" % missing)
        prev = _load_previous(log)
        if prev:
            for a in missing:
                keep = [i for i in prev.get("items", []) if i.get("ag") == a]
                if keep:
                    for i in keep:
                        rows.append(dict(agency=i["ag"], menu="", category=i.get("ht", ""),
                                         title=i.get("t", ""), url=i.get("u", ""),
                                         region_hint=i.get("sd", ""), posted=i.get("p", ""),
                                         deadline=i.get("d", ""), status=i.get("s", "")))
                    stale[a] = {"count": len(keep), "asof": prev.get("built", "")}
                    log("    %s %d건 복원 (기준 %s)" % (a, len(keep), prev.get("built", "")))

    seen, items = set(), []
    for r in rows:
        key = (r["agency"], r["title"], r.get("posted", ""))
        if key in seen:
            continue
        seen.add(key)
        sido, gu = classify.detect_region(r.get("title", ""), r.get("region_hint", ""), r["agency"])
        items.append({
            "ag": r["agency"],
            "t": r.get("title", ""),
            "u": r.get("url", ""),
            "sd": sido, "gu": gu,
            "dl": classify.detect_deal(r.get("title", ""), r.get("category", "")),
            "ht": classify.detect_house_type(r.get("title", ""), r.get("category", "")),
            "q": classify.detect_quals(r.get("title", "")),
            "k": classify.detect_kind(r.get("title", ""), r.get("category", "")),
            "p": r.get("posted", ""),
            "d": r.get("deadline", ""),
            "s": r.get("status", ""),
        })
    items.sort(key=lambda x: x["p"] or "", reverse=True)

    DIST.mkdir(exist_ok=True)
    payload = {
        "built": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
                 .isoformat(timespec="seconds"),
        "count": len(items),
        "errors": errors,
        "stale": stale,          # 갱신 실패해 직전 데이터를 재사용한 기관
        "items": items,
    }
    (DIST / "data.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # 정적 프론트 복사
    for f in WEB.iterdir():
        if f.is_file():
            shutil.copy2(f, DIST / f.name)

    log("=" * 46)
    log("정적 빌드 완료: %d건 -> %s" % (len(items), DIST / "data.json"))
    if errors:
        log("[!] 수집 오류: %s" % errors)
        # 수집이 통째로 실패하면 배포를 막아 낡은 데이터가 덮이는 것을 방지
        if len(items) == 0:
            raise SystemExit("수집 0건 - 배포 중단")
    else:
        log("수집 오류 없음")
    return payload


if __name__ == "__main__":
    build(int(sys.argv[1]) if len(sys.argv) > 1 else 3)
