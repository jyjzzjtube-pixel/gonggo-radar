# -*- coding: utf-8 -*-
"""공공공고 레이더 - LH/SH/GH 공고 통합 검색 웹앱 (PC 전용, 로컬 :5095)"""
import sys, io, os, json, threading, datetime, pathlib, subprocess

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from flask import Flask, render_template, request, jsonify

import store, classify

BASE = pathlib.Path(__file__).resolve().parent
app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

_collect_state = {"running": False, "log": [], "finished": None}

SIDO_LIST = ["서울", "경기", "인천", "부산", "대구", "광주", "대전", "울산", "세종",
             "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주", "전국"]
DEALS = ["임대(전세)", "임대(월세)", "매매(분양·매각)", "상가·업무", "토지", "기타"]
QUAL_LIST = list(classify.QUALS.keys())


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/app/")
@app.route("/app/<path:fn>")
def static_app(fn="index.html"):
    """배포될 정적 PWA(dist)를 로컬에서 그대로 미리보기"""
    from flask import send_from_directory
    return send_from_directory(str(BASE / "dist"), fn)


@app.route("/api/meta")
def api_meta():
    return jsonify({
        "sido": SIDO_LIST, "deals": DEALS, "quals": QUAL_LIST,
        "agencies": ["LH", "SH", "GH"],
        "prefs": store.list_prefs(),
        "stats": store.stats(),
        "last_run": store.last_run(),
        "collecting": _collect_state["running"],
    })


@app.route("/api/pref")
def api_pref():
    return jsonify(store.get_pref(request.args.get("name", "우리 조건")))


@app.route("/api/pref", methods=["POST"])
def api_pref_save():
    p = request.get_json(force=True)
    if not p.get("name"):
        return jsonify({"ok": False, "error": "이름 필요"}), 400
    store.save_pref(p)
    return jsonify({"ok": True})


@app.route("/api/search", methods=["POST"])
def api_search():
    body = request.get_json(force=True) or {}
    pref = body.get("pref") or store.get_pref()
    f = body.get("filters") or {}
    rows = store.query(pref, f, limit=int(body.get("limit", 400)))
    return jsonify({"count": len(rows), "rows": rows})


def _run_collect(pages):
    _collect_state["running"] = True
    _collect_state["log"] = []
    try:
        import collectors
        started = datetime.datetime.now().isoformat(timespec="seconds")

        def log(m):
            _collect_state["log"].append(str(m))
        rows, errors = collectors.collect_all(pages=pages, log=log)
        total, new = store.upsert(rows)
        store.log_run(started, total, new, errors)
        log("완료: 수집 %d건 / 신규 %d건" % (total, new))
        if errors:
            log("[!] 오류: %s" % errors)
    except Exception as e:
        _collect_state["log"].append("[!] 실패 %s: %s" % (type(e).__name__, e))
    finally:
        _collect_state["running"] = False
        _collect_state["finished"] = datetime.datetime.now().isoformat(timespec="seconds")


@app.route("/api/collect", methods=["POST"])
def api_collect():
    if _collect_state["running"]:
        return jsonify({"ok": False, "error": "이미 수집 중"}), 409
    pages = int((request.get_json(silent=True) or {}).get("pages", 3))
    threading.Thread(target=_run_collect, args=(pages,), daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/collect/status")
def api_collect_status():
    return jsonify(_collect_state)


if __name__ == "__main__":
    store.init()
    port = int(os.environ.get("RADAR_PORT", "5095"))
    print("공공공고 레이더 -> http://127.0.0.1:%d" % port)
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
