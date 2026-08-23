/* 소득·자산 자격 판정 엔진
 *
 * 기준값 출처: SH 공식 "2026년 도시근로자 가구원수별 가구당 월평균소득 기준" 표
 *   https://www.i-sh.co.kr/app/lay2/S48T1587C589/contents.do/
 *   (표의 70% / 140% 값에서 역산, 두 값이 동일하게 나와 교차검증됨)
 *
 * 주의: 아래 유형별 소득요건은 각 제도의 일반적인 기준을 정리한 것이며,
 *       실제 요건은 개별 공고문마다 다르다. 앱은 "거를 것을 거르는" 1차 선별용이고,
 *       최종 판단은 반드시 공고문 원문을 따라야 한다.
 */

/* 1·2인 가구 소득기준 가산 (%p)
 * 공공주택 소득기준은 1인가구 +20%p, 2인가구 +10%p를 가산해 적용한다.
 * 검증: GH 다산진건데시앙 공고문(26.08.13) 실측값과 정확히 일치
 *   1인 100% -> 3,813,363 x 1.20 = 4,576,036원 (공고문 표기값과 동일)
 *   2인 100% -> 5,866,270 x 1.10 = 6,452,897원 (공고문 표기값과 동일)
 * 위 공고문은 전용 60㎡ 초과 기준이며, 60㎡ 이하는 공고별로 다를 수 있다. */
const SMALL_HH_BONUS = { 1: 20, 2: 10 };

// 2026년 도시근로자 가구원수별 월평균소득 100% (원, 가산 적용 전 원값)
const INCOME_100 = {
  1: 3813363,   // 105% 4,004,031 에서 역산
  2: 5866270,   // 70% 4,106,389 / 140% 8,212,778 교차검증
  3: 8168429,
  4: 8802202,
  5: 9326985,
  6: 9906263,
};

/* 주택유형별 소득요건 (도시근로자 월평균소득 대비 %)
 *   single : 외벌이 기준 한도
 *   dual   : 맞벌이(본인·배우자 모두 소득) 기준 한도
 *   null   : 소득요건 없음
 *   other  : 다른 척도(기준중위소득 등)를 쓰므로 이 앱에서 판정하지 않음        */
const RULES = [
  // pr(우선순위) 낮을수록 먼저. 실제 공급제도를 나타내는 키가 브랜드명보다 앞선다.
  // 예: "신혼희망타운 행복주택"은 임대형이므로 행복주택 소득요건을 따른다.
  { key: "영구임대",       pr: 1, single: 'other', note: "기초생활수급자 등 별도 자격" },
  { key: "국민임대",       pr: 1, single: 70,  dual: 90,  note: "전용 50㎡ 미만은 더 낮음" },
  { key: "행복주택",       pr: 1, single: 100, dual: 120, note: "신혼부부 기준(임대형)" },
  { key: "통합공공임대",    pr: 1, single: 'other', note: "기준중위소득 척도(150% 등)" },
  { key: "매입임대",       pr: 1, single: 100, dual: 120, note: "유형별 상이(청년·신혼Ⅰ/Ⅱ)" },
  { key: "전세임대",       pr: 1, single: 100, dual: 120, note: "유형별 상이" },
  { key: "든든전세",       pr: 1, single: null, note: "소득요건 없음(무주택 요건 위주)" },
  { key: "장기전세",       pr: 1, single: 100, dual: 120, note: "면적별 상이(60㎡이하 105% 등)" },
  { key: "고령자복지주택",  pr: 1, single: 'other', note: "고령자 대상" },
  { key: "기숙사",         pr: 1, single: 'other' },
  { key: "청년안심주택",    pr: 2, single: 100, dual: 120, note: "청년·신혼 유형별 상이" },
  { key: "신혼희망타운",    pr: 3, single: 130, dual: 200, note: "분양형. LH 공식 맞벌이 200% 이하" },
  { key: "공공분양",       pr: 3, single: 130, dual: 200, note: "신혼특공 기준. 일반공급 60㎡초과는 소득요건 없음" },
  { key: "분양전환",       pr: 3, single: 130, dual: 200 },
];

// 소득요건이 원래 없는 거래유형
const NO_INCOME_DEALS = ["매매(분양·매각)", "상가·업무", "토지"];

/* 판정 결과
 *   ok      : 신청 가능 (또는 소득요건 없음)
 *   maybe   : 조건부 — 맞벌이 특례로 가능하거나 공고별 편차가 큼
 *   no      : 소득 초과로 사실상 불가
 *   unknown : 이 앱이 판정하지 않는 척도 / 정보 부족                        */
function judge(row, pref) {
  const inc = Number(pref.income || 0);          // 월 부부합산 소득(원)
  const dual = !!pref.dual;                      // 맞벌이 여부
  const size = Number(pref.household || 2);      // 가구원수
  const base = INCOME_100[size] || INCOME_100[2];
  const pct = inc ? (inc / base * 100) : null;

  if (!inc) return { v: 'unknown', pct: null, msg: '소득 미입력' };

  const hay = (row.ht || '') + ' ' + (row.t || '');
  const cands = RULES.filter(r => hay.includes(r.key));
  // 우선순위(pr) -> 더 구체적인(긴) 키 순
  const hit = cands.length
    ? cands.sort((a, b) => a.pr - b.pr || b.key.length - a.key.length)[0]
    : null;
  // 유형이 안 잡히는 경우에만 거래유형으로 판단한다.
  // (공공분양·신혼희망타운은 '매매'로 분류되지만 소득요건이 있으므로 위에서 먼저 잡혀야 한다)
  if (!hit) {
    if (NO_INCOME_DEALS.includes(row.dl))
      return { v: 'ok', pct, msg: '소득요건 없는 유형(매각·상가·토지 등)' };
    return { v: 'unknown', pct, msg: '유형 미식별 — 공고문 확인' };
  }

  if (hit.single === 'other')
    return { v: 'unknown', pct, msg: (hit.note || '') + ' — 공고문 확인' };
  if (hit.single === null)
    return { v: 'ok', pct, msg: hit.note || '소득요건 없음' };

  const rawPct = dual ? (hit.dual || hit.single) : hit.single;
  const bonus = SMALL_HH_BONUS[size] || 0;      // 1인 +20%p, 2인 +10%p
  const limitPct = rawPct + bonus;
  const limit = base * limitPct / 100;
  const label = `${hit.key} 한도 ${rawPct}%`
    + (bonus ? `+${bonus}%p(${size}인가구)=${limitPct}%` : '')
    + ` (${Math.round(limit).toLocaleString()}원)`;

  if (inc <= limit * 0.95) return { v: 'ok', pct, msg: label };
  if (inc <= limit)        return { v: 'maybe', pct, msg: label + ' — 경계선, 산정방식 따라 갈림' };
  return { v: 'no', pct, msg: label + ` — 우리 소득 ${Math.round(pct)}% 초과` };
}

/* 면적: 공고 목록에는 전용면적이 없다. 유형으로만 대략 추정한다. */
const SMALL_TYPES = ["행복주택", "청년안심주택", "기숙사", "원룸", "도시형생활주택", "1인가구"];
function areaHint(row, minArea) {
  if (!minArea) return null;
  const t = (row.t || '') + (row.ht || '');
  const m = t.match(/(\d{2})\s*(?:㎡|형|타입)/);
  if (m) {
    const a = +m[1];
    return a >= minArea ? { v: 'ok', msg: `제목상 ${a}㎡` } : { v: 'no', msg: `제목상 ${a}㎡ — 희망 ${minArea}㎡ 미만` };
  }
  if (SMALL_TYPES.some(k => t.includes(k)))
    return { v: 'maybe', msg: `${minArea}㎡ 이상 물량이 드문 유형 — 원문 확인` };
  return { v: 'unknown', msg: '면적은 공고문 확인 필요' };
}

/* 거주지 요건 힌트
 * SH 공고는 대부분 "공고일 현재 서울특별시 거주 무주택세대구성원"을 요구하고,
 * GH도 경기도 거주자 우선공급이 흔하다. LH는 사업지구 소재지 우선 + 전국 순.
 * 현재 거주지가 다르면 신청 자체가 막히거나 후순위가 되므로 미리 알려준다. */
function residencyHint(row, pref) {
  const live = (pref.liveSido || '').trim();     // 예: "경기"
  if (!live) return null;
  if (row.ag === 'SH' && live !== '서울')
    return { v: 'warn', msg: `SH는 서울 거주자 요건이 흔함 — 현재 ${live} 거주` };
  if (row.ag === 'GH' && live !== '경기')
    return { v: 'warn', msg: `GH는 경기도 거주자 우선 — 현재 ${live} 거주` };
  if (row.ag === 'LH' && row.sd && row.sd !== '전국' && row.sd !== live)
    return { v: 'info', msg: `${row.sd} 지역 거주자 우선공급 가능성 — 현재 ${live} 거주` };
  return { v: 'ok', msg: '거주지 요건 무난' };
}
