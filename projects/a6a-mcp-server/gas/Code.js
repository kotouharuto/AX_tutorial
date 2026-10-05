/**
 * A-6a：問い合わせ記録シートを JSON で返すウェブアプリ
 *
 * MCP サーバ（Python）から POST で呼ばれ、A-1 の「回答」シートの内容を返す。
 *
 * 【設計の要点】
 * 1. トークンは POST の本文で受け取る。
 *    GAS のウェブアプリは HTTP ヘッダを受け取れない（イベントオブジェクトに項目が無い）。
 *    URL のクエリに載せるとアクセスログや履歴に残るので、本文に入れる。
 * 2. 個人を特定できる列（お名前・メールアドレス・担当者）は返さない。
 *    「どの列を返すか」をここで決めておけば、Python 側の間違いで漏れることがない。
 * 3. HTTP のステータスコードは常に 200 になる（ContentService では変えられない）。
 *    そのため成功・失敗は本文の ok で表す。呼び出し側は ok を必ず見ること。
 * 4. シートは SpreadsheetApp ではなく Sheets API（高度なサービス）で読む。
 *    SpreadsheetApp は読み取り専用のスコープ（spreadsheets.readonly）を受け付けず、
 *    openById には読み書きのスコープ（spreadsheets）が要る。
 *    このウェブアプリは「全員」に公開して所有者の権限で動くので、
 *    読むだけの入口に全シートの編集権限を持たせない。Sheets API は readonly で読める。
 */

/**
 * 【権限承認用】エディタからこの関数を1回実行して、シートの読み取りを承認する。
 *
 * ファイルの先頭に置いているのは意図的。エディタは先頭の関数を既定で選ぶので、
 * 別の関数が先頭にあると「承認したのに何も起きない」状態になる（A-1 で踏んだ）。
 */
function authorize() {
  const values = readSheetValues();
  // ここまで来れば承認は済んでいる。行数だけ記録して、中身はログに出さない（個人情報のため）
  Logger.log('承認OK：回答シートの行数 = ' + values.length);
}

/** 読み取るシートの名前（A-1 の Config.js と同じ） */
const SHEET_NAME = '回答';

/**
 * Claude に渡す列。シートの見出しの名前で指定し、返すときの名前に読み替える。
 * ここに無い列（お名前・メールアドレス・担当者）は返さない。
 */
const EXPOSED_COLUMNS = {
  'タイムスタンプ': 'timestamp',
  '問い合わせ内容': 'content',
  '分類': 'category',
  '緊急度': 'urgency',
  '状態': 'status',
  '詳細': 'detail',
};

/** 1回で返す件数の上限。大量に返すと Claude の文脈を圧迫するため */
const MAX_LIMIT = 50;
const DEFAULT_LIMIT = 20;

/**
 * POST を受け取る入口。ウェブアプリとして公開すると、この名前の関数が呼ばれる。
 *
 * @param {Object} e リクエストの情報。本文は e.postData.contents に文字列で入っている
 * @returns {TextOutput} JSON の応答
 */
function doPost(e) {
  try {
    const request = parseRequest(e);
    checkToken(request.token);
    const rows = readRows(request);
    return jsonResponse({ ok: true, total: rows.total, returned: rows.items.length, rows: rows.items });
  } catch (err) {
    // 想定済みの失敗（RequestError）はその文言を返す。
    // それ以外は中身を返さない（シートの内容や内部情報が混ざる可能性があるため）。
    if (err instanceof RequestError) {
      return jsonResponse({ ok: false, error: err.message });
    }
    console.error(err); // 実行ログ（エディタの「実行数」）には残す
    return jsonResponse({ ok: false, error: 'サーバ内部のエラー。GAS の実行ログを確認すること' });
  }
}

/**
 * 想定済みの失敗を表すエラー。呼び出し側に文言をそのまま見せてよいもの。
 * MCP の ToolError と同じ考え方で、「説明させたい失敗」と「想定外の失敗」を分ける。
 */
class RequestError extends Error {}

/** 本文を JSON として読み、値を検査する */
function parseRequest(e) {
  if (!e || !e.postData || !e.postData.contents) {
    throw new RequestError('本文が空。JSON で token を送ること');
  }
  let body;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (_) {
    throw new RequestError('本文が JSON として読めない');
  }

  const limit = body.limit === undefined ? DEFAULT_LIMIT : Number(body.limit);
  // Number.isInteger で、小数や数値でない値（"abc" → NaN）をまとめて弾く
  if (!Number.isInteger(limit) || limit < 1 || limit > MAX_LIMIT) {
    throw new RequestError('limit は 1〜' + MAX_LIMIT + ' の整数で指定すること');
  }
  return {
    token: body.token,
    status: body.status || null,
    category: body.category || null,
    limit: limit,
  };
}

/**
 * トークンを照合する。
 *
 * 【失敗側に倒す】サーバ側にトークンが設定されていないときは、必ず拒否する。
 * これを忘れると「設定なし（undefined）」と「送られてこない（undefined）」が
 * 一致してしまい、誰でも読めるようになる。
 */
function checkToken(token) {
  const expected = PropertiesService.getScriptProperties().getProperty('API_TOKEN');
  if (!expected) {
    throw new RequestError('サーバ側でトークンが設定されていない（スクリプトプロパティ API_TOKEN）');
  }
  if (typeof token !== 'string' || token !== expected) {
    // どちらが違うかは言わない（推測の手がかりを与えないため）
    throw new RequestError('認証に失敗した');
  }
}

/**
 * シートの全セルを読む。ID はスクリプトプロパティから読む（コードに書かない）。
 *
 * 【SpreadsheetApp との違い】Sheets API は**行の末尾の空セルを省略して返す。**
 * 行ごとに長さが違う配列になるので、読む側で「無い＝空」と扱う（cellAt を参照）。
 * また既定では表示用の文字列で返る（日付も「2026/09/01 10:00:00」のような文字列）。
 */
function readSheetValues() {
  const id = PropertiesService.getScriptProperties().getProperty('SHEET_ID');
  if (!id) {
    throw new RequestError('サーバ側でシートが設定されていない（スクリプトプロパティ SHEET_ID）');
  }
  let response;
  try {
    // シート名に記号が入っても範囲として読めるように、単引用符で囲む
    response = Sheets.Spreadsheets.Values.get(id, "'" + SHEET_NAME + "'");
  } catch (err) {
    console.error(err); // 詳細は実行ログに残し、呼び出し側には対処できる情報だけ返す
    throw new RequestError(
      'シートを読めない。SHEET_ID が正しいか、シート「' + SHEET_NAME + '」があるか確認すること'
    );
  }
  return response.values || []; // シートが空なら values が無い
}

/** 行の i 番目のセル。Sheets API は末尾の空セルを省略するので、無ければ空文字 */
function cellAt(row, i) {
  return i < row.length ? row[i] : '';
}

/**
 * 行を読み、条件で絞り込み、新しい順に limit 件返す。
 * 列は見出しの名前で探す（列の位置が変わっても壊れないように）。
 */
function readRows(request) {
  const values = readSheetValues();
  if (values.length < 2) {
    return { total: 0, items: [] }; // 見出ししか無い
  }
  const header = values[0];

  // 見出しの名前 → 列番号。返す列が1つでも見つからなければ止める。
  // 黙って空欄で返すと「中身が空」が正常に見えてしまう（A-5a で踏んだ型）
  const index = {};
  Object.keys(EXPOSED_COLUMNS).forEach(function (name) {
    const i = header.indexOf(name);
    if (i === -1) {
      throw new RequestError('シートに列「' + name + '」が無い。見出しが変わっていないか確認すること');
    }
    index[name] = i;
  });

  const matched = values.slice(1)
    .filter(function (row) { return cellAt(row, index['タイムスタンプ']) !== ''; }) // 空行を除く
    .filter(function (row) { return !request.status || cellAt(row, index['状態']) === request.status; })
    .filter(function (row) { return !request.category || cellAt(row, index['分類']) === request.category; });

  const items = matched
    .reverse() // 下にあるほど新しいので、新しい順にする
    .slice(0, request.limit)
    .map(function (row) {
      const item = {};
      Object.keys(EXPOSED_COLUMNS).forEach(function (name) {
        item[EXPOSED_COLUMNS[name]] = String(cellAt(row, index[name]));
      });
      return item;
    });
  return { total: matched.length, items: items };
}

/** JSON の応答を作る */
function jsonResponse(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
