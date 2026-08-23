/* 회귀검사 — 한 번 고친 결함이 되살아나지 않도록 고정한다.
 * 실행: node test_regression.js   (종료코드 0=통과, 1=실패)
 * CI(GitHub Actions)에서 빌드 직후 실행되어 실패 시 배포를 막는다. */
const fs = require('fs');
const path = require('path');

const ROOT = __dirname;
const results = [];
let failed = 0;

function check(name, actual, expected, note) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  results.push({ ok, name, actual, expected, note });
  if (!ok) failed++;
}
function checkTrue(name, cond, note) {
  results.push({ ok: !!cond, name, actual: !!cond, expected: true, note });
  if (!cond) failed++;
}

// ── 판정 엔진 로드 ────────────────────────────────────────────
const src = fs.readFileSync(path.join(ROOT, 'web', 'eligibility.js'), 'utf8');
const api = new Function(src + '; return {judge, areaHint, residencyHint, INCOME_100, SMALL_HH_BONUS, RULES};')();
const { judge, areaHint, residencyHint, INCOME_100, SMALL_HH_BONUS } = api;

/* [회귀 1] 1·2인가구 소득 가산 (+20%p / +10%p)
 * 2026-08-23 결함: 가산을 빼먹어 한도를 낮게 잡아 136건을 "소득초과"로 오판했다.
 * 기준값 출처: GH 다산진건데시앙 모집공고문(26.08.13) 표기값 */
[[1, 100, 4576036], [1, 120, 5338708], [2, 100, 6452897], [2, 120, 7626151]].forEach(([hh, pct, exp]) => {
  const got = Math.round(INCOME_100[hh] * (pct + (SMALL_HH_BONUS[hh] || 0)) / 100);
  checkTrue(`소득한도 ${hh}인가구 ${pct}% = ${exp.toLocaleString()}원`, Math.abs(got - exp) <= 1,
    `계산 ${got.toLocaleString()}`);
});
check('3인 이상은 가산 없음', SMALL_HH_BONUS[3] || 0, 0);

/* [회귀 2] 유형 매칭 우선순위
 * "신혼희망타운 행복주택"은 임대형이므로 행복주택(100%) 기준을 따라야 한다.
 * 브랜드명인 신혼희망타운(130/200%)이 먼저 잡히면 한도를 과대평가한다. */
const P2 = { income: 10000000, household: 2, dual: true };
const rentalHope = { ag: 'LH', ht: '신혼희망타운', t: '남양주진접2 A-4BL 신혼희망타운 행복주택 최초 입주자 모집공고', dl: '임대(월세)' };
checkTrue('신혼희망타운 행복주택 -> 행복주택 기준 적용', judge(rentalHope, P2).msg.startsWith('행복주택'),
  judge(rentalHope, P2).msg);
const saleHope = { ag: 'LH', ht: '신혼희망타운', t: '성남복정2 A1블록 신혼희망타운(공공분양) 입주자모집공고', dl: '매매(분양·매각)' };
checkTrue('신혼희망타운 공공분양 -> 소득요건 적용(요건없음 아님)', /신혼희망타운|공공분양/.test(judge(saleHope, P2).msg),
  judge(saleHope, P2).msg);

/* [회귀 3] 맞벌이/외벌이가 실제로 분기해야 한다
 * 결함 이력: NO_INCOME_DEALS를 먼저 검사해 분양 건이 전부 "요건없음"으로 빠져
 * 맞벌이/외벌이 판정 결과가 완전히 동일했다. */
const single = judge(saleHope, { income: 10000000, household: 2, dual: false });
const dual = judge(saleHope, { income: 10000000, household: 2, dual: true });
checkTrue('맞벌이/외벌이 판정이 분기함', single.v !== dual.v, `외벌이=${single.v} 맞벌이=${dual.v}`);

/* [회귀 4] 순수 매각·토지·상가는 소득요건 없음 */
const land = { ag: 'LH', ht: '토지', t: '구리갈매역세권 근린생활시설용지 공급공고', dl: '토지' };
check('토지는 소득요건 없음', judge(land, P2).v, 'ok');

/* [회귀 5] 거주지 요건 경고 (구리 거주 -> SH 서울 물량 경고) */
const shRow = { ag: 'SH', sd: '서울', gu: '', t: '서울 매입임대', dl: '임대(월세)' };
check('구리 거주 -> SH 경고', residencyHint(shRow, { liveSido: '경기' }).v, 'warn');

/* [회귀 6] 수집 데이터 무결성 */
const distData = path.join(ROOT, 'dist', 'data.json');
if (fs.existsSync(distData)) {
  const d = JSON.parse(fs.readFileSync(distData, 'utf8'));
  checkTrue('수집 건수 > 0', d.count > 0, `${d.count}건`);
  const badUrl = d.items.filter(i => !(i.u || '').startsWith('http'));
  check('원문 링크 불량 0건', badUrl.length, 0);
  const noTitle = d.items.filter(i => !i.t);
  check('제목 누락 0건', noTitle.length, 0);
  const agencies = [...new Set(d.items.map(i => i.ag))].sort();
  check('3사 모두 수집됨', agencies, ['GH', 'LH', 'SH']);
} else {
  results.push({ ok: true, name: 'dist/data.json 없음 - 수집 검사 건너뜀', actual: 'skip', expected: 'skip' });
}

/* [회귀 7] 터치타겟 44px — CSS에 min-height가 남아있는지 정적 검사
 * (실측은 브라우저에서, 여기서는 규칙이 삭제되지 않았는지만 지킨다) */
const html = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
['.iconbtn', '.tab{', '.sel{', '.chip{', '.num{'].forEach(sel => {
  const i = html.indexOf(sel);
  const block = i >= 0 ? html.slice(i, i + 260) : '';
  checkTrue(`${sel} 44px 보장`, /min-height:44px|height:44px/.test(block), block ? '규칙 없음' : '셀렉터 없음');
});

// ── 출력 ──────────────────────────────────────────────────────
console.log('회귀검사 — 공공공고 레이더\n' + '='.repeat(58));
results.forEach(r => {
  console.log(`${r.ok ? 'PASS' : 'FAIL'}  ${r.name}` +
    (r.ok ? '' : `\n        기대=${JSON.stringify(r.expected)} 실제=${JSON.stringify(r.actual)}` +
      (r.note ? ` (${r.note})` : '')));
});
console.log('='.repeat(58));
console.log(`${results.length - failed}/${results.length} 통과${failed ? `, ${failed}건 실패` : ''}`);
process.exit(failed ? 1 : 0);
