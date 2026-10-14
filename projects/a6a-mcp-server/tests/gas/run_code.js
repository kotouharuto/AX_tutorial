/**
 * Code.js を Node で動かす検査。GAS の部品（Sheets・PropertiesService・ContentService）を偽物に差し替える。
 *
 * 【なぜ必要か】GAS は手元で実行できない。デプロイしてから論理の誤りが見つかると、
 * push → 承認 → 実行の往復が増える。ここで doPost を実際に動かしておく。
 *
 * 実行：node tests/gas/run_code.js
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const CODE = fs.readFileSync(path.join(__dirname, '..', '..', 'gas', 'Code.js'), 'utf8');

// Sheets API は行の末尾の空セルを省略して返す。それを再現する（2行目は「詳細」以降が無い）
const HEADER = ['タイムスタンプ', 'お名前', 'メールアドレス', '問い合わせ内容', '分類', '緊急度', '担当者', '状態', '詳細'];
const SHEET = [
  HEADER,
  ['2026/09/01 10:00:00', '山田', 'yamada@example.com', 'VPN に繋がらない', 'システム障害', '高', 'it@example.com', '完了', ''],
  ['2026/09/02 11:00:00', '佐藤', 'sato@example.com', '経費の締め日は？', '申請手続き', '低', 'soumu@example.com', '未分類'],
  [], // 途中の空行（Sheets API は空配列で返す）
  // --- 実データで漏れた形の再現（値は架空）---
  // 列ずれ：「状態」にメールアドレスが入った
  ['2026/09/03 09:00:00', '鈴木', 'suzuki@example.com', '議事録システムが止まった', 'システム障害', '高', 'it@example.com', 'suzuki@example.com', ''],
  // 「内容」がメールアドレスだけ
  ['2026/09/04 09:00:00', '田中', 'tanaka@example.com', 'tanaka@example.com', 'システム障害', '高', 'it@example.com', '完了', ''],
  // 本文に本人の氏名と、別人のメールアドレスが書かれている
  ['2026/09/05 09:00:00', '高橋 花子', 'hanako@example.com', '高橋 花子です。上司の other@example.org にも共有してください', 'その他', '低', 'soumu@example.com', '完了', ''],
  // 分類が想定外（列ずれ）
  ['2026/09/06 09:00:00', '伊藤', 'ito@example.com', '備品が届かない', '伊藤', '中', 'soumu@example.com', '完了', ''],
];

function load({ props = {}, values = SHEET, throwOnGet = false } = {}) {
  const logs = [];
  const sandbox = {
    console: { error: (e) => logs.push(String(e)), log: () => {} },
    Logger: { log: (m) => logs.push(m) },
    PropertiesService: {
      getScriptProperties: () => ({ getProperty: (k) => (k in props ? props[k] : null) }),
    },
    Sheets: {
      Spreadsheets: {
        Values: {
          get: (id, range) => {
            if (throwOnGet) throw new Error('Unable to parse range: ' + range);
            return values.length ? { values: values } : {};
          },
        },
      },
    },
    ContentService: {
      MimeType: { JSON: 'application/json' },
      createTextOutput: (text) => ({ text: text, setMimeType() { return this; } }),
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(CODE, sandbox);
  return { sandbox, logs };
}

const PROPS = { SHEET_ID: 'sheet-id', API_TOKEN: 'secret-token' };

function post(ctx, body) {
  const out = ctx.sandbox.doPost({ postData: { contents: JSON.stringify(body) } });
  return JSON.parse(out.text);
}

let passed = 0;
function check(name, fn) {
  fn();
  passed += 1;
  console.log('  OK  ' + name);
}

check('正しいトークンで新しい順に返る', () => {
  const r = post(load({ props: PROPS }), { token: 'secret-token' });
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.total, 6, '空行を除いて6件');
  assert.strictEqual(r.rows[0].timestamp, '2026/09/06 09:00:00', '新しい順');
});

check('末尾の空セルが省略された行でも、詳細は空文字になる', () => {
  const r = post(load({ props: PROPS }), { token: 'secret-token', status: '未分類' });
  assert.strictEqual(r.rows[0].detail, '', 'undefined ではなく空文字');
});

check('個人を特定できる列を返さない', () => {
  const r = post(load({ props: PROPS }), { token: 'secret-token' });
  const text = JSON.stringify(r);
  for (const leaked of ['山田', 'yamada@example.com', 'it@example.com', '"お名前"', '"担当者"']) {
    assert.ok(!text.includes(leaked), '漏れている: ' + leaked);
  }
});

check('状態で絞り込める', () => {
  const r = post(load({ props: PROPS }), { token: 'secret-token', status: '未分類' });
  assert.strictEqual(r.total, 1);
});

check('トークン違いは拒否', () => {
  const r = post(load({ props: PROPS }), { token: 'wrong' });
  assert.deepStrictEqual([r.ok, r.error], [false, '認証に失敗した']);
});

check('サーバ側にトークンが無ければ、トークン無しの要求も拒否する（undefined 同士の一致を防ぐ）', () => {
  const r = post(load({ props: { SHEET_ID: 'sheet-id' } }), {});
  assert.strictEqual(r.ok, false);
  assert.ok(r.error.includes('API_TOKEN'));
});

check('limit の範囲外・非整数は拒否', () => {
  for (const limit of [0, 51, 2.5, 'abc']) {
    const r = post(load({ props: PROPS }), { token: 'secret-token', limit: limit });
    assert.strictEqual(r.ok, false, 'limit=' + limit);
  }
});

check('シートを読めないときは対処の手がかりを返し、内部の詳細は返さない', () => {
  const ctx = load({ props: PROPS, throwOnGet: true });
  const r = post(ctx, { token: 'secret-token' });
  assert.strictEqual(r.ok, false);
  assert.ok(r.error.includes('SHEET_ID'));
  assert.ok(!r.error.includes('Unable to parse'), '内部のエラー文が漏れている');
  assert.ok(ctx.logs.some((l) => l.includes('Unable to parse')), '実行ログには残す');
});

check('見出しが変わっていたら空欄で返さず止める', () => {
  const broken = [['タイムスタンプ', '問い合わせ内容', '分類', '緊急度', '状態']]; // 「詳細」が無い
  const r = post(load({ props: PROPS, values: broken.concat([['x', 'y', 'z', 'w', 'v']]) }), { token: 'secret-token' });
  assert.strictEqual(r.ok, false);
  assert.ok(r.error.includes('詳細'));
});

check('本文が JSON でなければ拒否', () => {
  const out = load({ props: PROPS }).sandbox.doPost({ postData: { contents: 'not json' } });
  assert.strictEqual(JSON.parse(out.text).ok, false);
});

check('authorize が行数をログに出す（中身は出さない）', () => {
  const ctx = load({ props: PROPS });
  ctx.sandbox.authorize();
  assert.ok(ctx.logs.some((l) => l === '承認OK：回答シートの行数 = 8'));
  assert.ok(!ctx.logs.some((l) => l.includes('山田')));
});

function rowAt(r, ts) {
  return r.rows.find((x) => x.timestamp === ts);
}

check('【実データの再現】列ずれで「状態」に入ったメールアドレスを伏せ、警告を付ける', () => {
  const r = post(load({ props: PROPS }), { token: 'secret-token' });
  const row = rowAt(r, '2026/09/03 09:00:00');
  assert.strictEqual(row.status, '[想定外の値]');
  assert.ok(row.warnings.some((w) => w.includes('状態')));
});

check('【実データの再現】「内容」がメールアドレスだけの行を伏せる', () => {
  const r = post(load({ props: PROPS }), { token: 'secret-token' });
  assert.strictEqual(rowAt(r, '2026/09/04 09:00:00').content, '[メールアドレス]');
});

check('本文中の本人の氏名と、別人のメールアドレスを伏せる', () => {
  const r = post(load({ props: PROPS }), { token: 'secret-token' });
  const content = rowAt(r, '2026/09/05 09:00:00').content;
  assert.ok(!content.includes('高橋 花子'), '氏名が残っている: ' + content);
  assert.ok(!content.includes('other@example.org'), '別人のアドレスが残っている');
  assert.ok(content.includes('[氏名]') && content.includes('[メールアドレス]'));
});

check('分類が想定外なら値ごと伏せる（氏名が分類に入った列ずれ）', () => {
  const r = post(load({ props: PROPS }), { token: 'secret-token' });
  const row = rowAt(r, '2026/09/06 09:00:00');
  assert.strictEqual(row.category, '[想定外の値]');
  assert.ok(row.warnings.some((w) => w.includes('分類')));
});

check('正常な行には警告が付かない', () => {
  const r = post(load({ props: PROPS }), { token: 'secret-token' });
  assert.deepStrictEqual(rowAt(r, '2026/09/01 10:00:00').warnings, []);
});

check('どの行のどの値にも、メールアドレスの形が残っていない', () => {
  const r = post(load({ props: PROPS }), { token: 'secret-token', limit: 50 });
  const text = JSON.stringify(r.rows);
  assert.ok(!/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/.test(text), '残っている: ' + text);
});

console.log('\n' + passed + ' 件すべて成功');
