# -*- coding: utf-8 -*-
"""수집 실행기 - LH/SH/GH 공고를 긁어 SQLite에 적재"""
import sys, io, os, datetime, pathlib

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import collectors, store

LOG_DIR = pathlib.Path(os.path.expanduser("~")) / "WORKSPACE" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def main(pages=3):
    started = datetime.datetime.now().isoformat(timespec="seconds")
    lines = []

    def log(msg):
        print(msg)
        lines.append(str(msg))

    store.init()
    rows, errors = collectors.collect_all(pages=pages, log=log)
    total, new = store.upsert(rows)
    store.log_run(started, total, new, errors)

    log("=" * 46)
    log("수집 %d건 / 신규 %d건" % (total, new))
    if errors:
        log("[!] 오류: %s" % errors)
    else:
        log("오류 없음")
    st = store.stats()
    log("DB 누적 %d건 %s" % (st["total"], st["by_agency"]))
    log("거래유형별: %s" % st["by_deal"])

    day = datetime.date.today().isoformat()
    with open(LOG_DIR / ("%s_gonggo_radar.md" % day), "a", encoding="utf-8") as f:
        f.write("\n## %s (device:galaxy_book)\n" % started)
        f.write("\n".join("- " + l for l in lines) + "\n")
    return 0 if not errors else 1


if __name__ == "__main__":
    p = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    sys.exit(main(p))
