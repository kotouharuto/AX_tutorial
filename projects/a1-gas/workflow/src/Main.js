/**
 * A-1 ステップ③：本体（フォーム受付 → 分類 → 振り分け → 記録）
 *
 * 【エントリポイント】フォーム送信トリガーから呼ばれる。
 * 手で実行しても e が undefined になるだけなので、動作確認は
 * testWithSampleRow() を使うこと。
 */

/**
 * フォーム送信時に実行される。
 * @param {GoogleAppsScript.Events.SheetsOnFormSubmit} e トリガーイベント
 */
function onFormSubmit(e) {
  if (!e || !e.range) {
    throw new Error(
      'イベント情報がありません。この関数はフォーム送信トリガーから実行してください。' +
      '手動で動作確認する場合は testWithSampleRow() を使ってください。'
    );
  }
  processRow_(e.range.getRow(), extractInquiry_(e.namedValues));
}

/**
 * イベントから問い合わせ内容を取り出す。
 * @param {Object<string, string[]>} namedValues フォーム項目名 → 回答配列
 * @returns {{name: string, email: string, body: string}} 問い合わせ内容
 */
function extractInquiry_(namedValues) {
  // namedValues は項目名をキーに配列で入る。フォームの項目名を変えると壊れる。
  // 壊れたときに黙って空文字で進まないよう、取り出しは1か所に集約する。
  const pick = (key) => String(namedValues?.[key]?.[0] ?? '').trim();
  return {
    name: pick('お名前'),
    email: pick('メールアドレス'),
    body: pick('問い合わせ内容'),
  };
}

/**
 * 1行を処理する。分類 → 振り分けメール → 記録。
 *
 * 【冪等性】状態列が既に埋まっている行は再処理しない。
 * ステップ④の多重起動対策の土台。LockService による排他は④で追加する
 * （ロックは同時実行を防ぐが、再実行までは防がないため両方要る）。
 * @param {number} row 対象行（1始まり）
 * @param {{name: string, email: string, body: string}} inquiry 問い合わせ内容
 */
function processRow_(row, inquiry) {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_RESPONSES);
  if (!sheet) {
    throw new Error(`${SHEET_RESPONSES} シートがありません。フォームから1件送信してください。`);
  }
  const cols = ensureExtraHeaders_(sheet);

  const current = String(sheet.getRange(row, cols.状態).getValue() ?? '').trim();
  if (current) {
    console.log(`行 ${row} は処理済み（状態: ${current}）のためスキップする。`);
    return;
  }

  try {
    const result = classifyInquiry(inquiry.body);
    const assignee = resolveAssignee_(result.category);

    sendAssignmentMail_(assignee.to, inquiry, result);

    writeResult_(sheet, row, cols, {
      分類: result.category,
      緊急度: result.urgency,
      担当者: assignee.to,
      状態: assignee.isFallback ? STATUS.UNCLASSIFIED : STATUS.DONE,
      詳細: assignee.isFallback
        ? `担当者未設定のためフォールバック送信。判断理由: ${result.reason}`
        : result.reason,
    });
  } catch (error) {
    // 【方針】エラーは握り潰さない。ただしトリガー実行なので投げ直すだけでは誰も気づかない。
    // シートに残す（業務側から見える）＋ 通知する（能動的に届く）の二重で出す。
    handleFailure_(sheet, row, cols, inquiry, error);
    throw error; // 実行履歴にも失敗として残す
  }
}

/**
 * 失敗をシートと通知の両方に出す。
 * @param {GoogleAppsScript.Spreadsheet.Sheet} sheet 回答シート
 * @param {number} row 対象行
 * @param {Object<string, number>} cols ヘッダ名 → 列番号
 * @param {{name: string, email: string, body: string}} inquiry 問い合わせ内容
 * @param {Error} error 発生したエラー
 */
function handleFailure_(sheet, row, cols, inquiry, error) {
  writeResult_(sheet, row, cols, {
    状態: STATUS.ERROR,
    詳細: error.message,
  });

  // 通知先が無い場合に通知処理で二次障害を起こさないよう、ここでは投げない。
  const to = PropertiesService.getScriptProperties().getProperty(PROP_FALLBACK_TO);
  if (!to) {
    console.error(`通知先（${PROP_FALLBACK_TO}）が未設定のため、エラー通知を送れない。`);
    return;
  }

  GmailApp.sendEmail(
    to,
    '[A1-workflow] 問い合わせの処理に失敗しました',
    [
      `行: ${row}`,
      `エラー: ${error.message}`,
      '',
      '対応が必要です。シートの「詳細」列も確認してください。',
      `シート: ${SpreadsheetApp.getActiveSpreadsheet().getUrl()}`,
    ].join('\n')
  );
}

/**
 * 担当者へ振り分けメールを送る。
 * @param {string} to 宛先
 * @param {{name: string, email: string, body: string}} inquiry 問い合わせ内容
 * @param {{category: string, urgency: string, reason: string}} result 分類結果
 */
function sendAssignmentMail_(to, inquiry, result) {
  GmailApp.sendEmail(
    to,
    `[問い合わせ/${result.category}/緊急度${result.urgency}] ${inquiry.name} 様`,
    [
      `分類: ${result.category}（緊急度: ${result.urgency}）`,
      `判断理由: ${result.reason}`,
      '',
      `お名前: ${inquiry.name}`,
      `返信先: ${inquiry.email}`,
      '',
      '--- 問い合わせ内容 ---',
      inquiry.body,
    ].join('\n')
  );
}

/**
 * 追加列のヘッダを確保し、ヘッダ名 → 列番号の対応を返す。
 * 既にあれば作らない（冪等）。
 *
 * フォームの回答シートは列が自動生成されるため、追加列は右端に足す。
 * 列位置を定数で固定すると、フォームに項目が増えた瞬間にずれて壊れる。
 * @param {GoogleAppsScript.Spreadsheet.Sheet} sheet 回答シート
 * @returns {Object<string, number>} ヘッダ名 → 列番号（1始まり）
 */
function ensureExtraHeaders_(sheet) {
  const lastColumn = sheet.getLastColumn();
  const headers = sheet.getRange(1, 1, 1, lastColumn).getValues()[0].map(String);

  const cols = {};
  EXTRA_HEADERS.forEach((name) => {
    const index = headers.indexOf(name);
    if (index !== -1) {
      cols[name] = index + 1;
    }
  });

  const missing = EXTRA_HEADERS.filter((name) => !cols[name]);
  missing.forEach((name, i) => {
    const column = lastColumn + i + 1;
    sheet.getRange(1, column).setValue(name);
    cols[name] = column;
  });

  return cols;
}

/**
 * 結果をシートに書く。渡された項目だけを更新する。
 * @param {GoogleAppsScript.Spreadsheet.Sheet} sheet 回答シート
 * @param {number} row 対象行
 * @param {Object<string, number>} cols ヘッダ名 → 列番号
 * @param {Object<string, string>} values ヘッダ名 → 書き込む値
 */
function writeResult_(sheet, row, cols, values) {
  Object.entries(values).forEach(([name, value]) => {
    if (cols[name]) {
      sheet.getRange(row, cols[name]).setValue(value);
    }
  });
}

/**
 * 【診断用】フォームを使わず、シートの指定行を手動で処理する。
 * トリガー経由でしか動かない処理は検証が面倒なので、入口を分けておく。
 * @param {number} row 処理したい行（省略時は最終行）
 */
function testWithSampleRow(row) {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_RESPONSES);
  if (!sheet) {
    throw new Error(`${SHEET_RESPONSES} シートがありません。フォームから1件送信してください。`);
  }
  const target = row || sheet.getLastRow();
  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0].map(String);
  const rowValues = sheet.getRange(target, 1, 1, sheet.getLastColumn()).getValues()[0];

  const byHeader = (name) => {
    const i = headers.indexOf(name);
    return i === -1 ? '' : String(rowValues[i] ?? '').trim();
  };

  processRow_(target, {
    name: byHeader('お名前'),
    email: byHeader('メールアドレス'),
    body: byHeader('問い合わせ内容'),
  });
}

/**
 * 【手動実行】状態が「エラー」の行だけを再処理する。
 *
 * 処理済み行をスキップする冪等性は多重起動対策として必要だが、
 * そのままだと失敗した行を作り直す経路が無くなる。
 * 「二重処理を防ぐ」と「失敗を回収する」は別の要件なので、入口を分けて両立させる。
 *
 * 自動リトライにしないのは意図的。原因を直さないまま再試行を繰り返すと、
 * API クォータを浪費した上で同じ失敗を積み上げるため
 * （リトライすべき一時障害の扱いはステップ④で実装する）。
 */
function retryFailedRows() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_RESPONSES);
  if (!sheet) {
    throw new Error(`${SHEET_RESPONSES} シートがありません。`);
  }
  const cols = ensureExtraHeaders_(sheet);
  const lastRow = sheet.getLastRow();

  let retried = 0;
  for (let row = 2; row <= lastRow; row++) {
    const status = String(sheet.getRange(row, cols.状態).getValue() ?? '').trim();
    if (status !== STATUS.ERROR) {
      continue;
    }
    // 状態を空に戻してから processRow_ に渡す。
    // これをしないと processRow_ の「処理済みならスキップ」に弾かれる。
    sheet.getRange(row, cols.状態).clearContent();
    sheet.getRange(row, cols.詳細).clearContent();

    testWithSampleRow(row);
    retried++;
  }
  console.log(`エラー行 ${retried} 件を再処理した。`);
}
