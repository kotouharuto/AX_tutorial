/**
 * A-1 ステップ④-1 と ④-3：6分制限と外部API失敗を同時に踏む実験
 *
 * 【目的】
 *   1. 100件超を API に投げて実行時間6分を超えさせ、強制終了を体験する
 *   2. その過程で無料枠のレート制限（429）に当て、指数バックオフの効果を見る
 *
 * 【本番と分ける理由】ステップ③のフォーム回答シートを汚さないため。
 * ただし分類処理そのものは本番の classifyInquiry を呼ぶ。
 * 実験用に別実装すると、確かめた対処が本番に入っていないことになる。
 */

const SHEET_BATCH = 'バッチデモ';

/** 投入する行数。6分を超えさせるために多めにする。 */
const BATCH_ROW_COUNT = 150;

/** 分割実行の再開位置を保存するキー。 */
const PROP_BATCH_CURSOR = 'BATCH_CURSOR';

/** 継続トリガーのハンドラ名。後始末で使うため定数化する。 */
const BATCH_HANDLER = 'demoBatchResume';

/**
 * 実験用に安全域を上書きするキー。
 *
 * 本番の既定（MAX_RUNTIME_MS = 4.5分）のままだと、残件が少ないときに
 * 中断が発動せず、分割実行の挙動を観測できない。
 * かといって件数を増やすと API 呼び出しを余分に消費する。
 *
 * 実務でも安全域は環境ごとに調整したくなる値（1件あたりの処理時間が違うため）なので、
 * 定数を直接書き換えるのではなく、上書き可能にしておく方が筋が良い。
 */
const PROP_BATCH_MAX_RUNTIME_MS = 'BATCH_MAX_RUNTIME_MS';

/**
 * 【手順1】実験用シートを作り、ダミーの問い合わせを投入する。
 * 実験のたびに初期化したいので、あえて冪等にしない。
 */
function demoBatchSetup() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = recreateSheet_(ss, SHEET_BATCH);

  sheet.getRange(1, 1, 1, 4).setValues([['ID', '内容', '分類', '状態']]);

  // 分類結果がばらけるよう、4カテゴリに対応する文面を循環させる。
  // 全部同じ文面だと、キャッシュ的な挙動で速く返る可能性があり、
  // 6分制限の検証としては条件が甘くなる。
  const templates = [
    'ポータルにログインできません。エラー画面が出ます。',
    '経費精算の申請方法を教えてください。締切はいつですか。',
    '会議室のプロジェクタが映りません。交換をお願いします。',
    '来客用の駐車場を予約したいのですが手順が分かりません。',
  ];

  const rows = [];
  for (let i = 1; i <= BATCH_ROW_COUNT; i++) {
    rows.push([
      `B${String(i).padStart(3, '0')}`,
      `${templates[i % templates.length]}（案件 ${i}）`,
      '',
      '',
    ]);
  }
  sheet.getRange(2, 1, rows.length, 4).setValues(rows);
  sheet.setFrozenRows(1);

  PropertiesService.getScriptProperties().deleteProperty(PROP_BATCH_CURSOR);

  console.log(`${SHEET_BATCH} に ${BATCH_ROW_COUNT} 件投入した。カーソルもリセットした。`);
  console.log('次に demoBatchUnsafe を実行して、6分制限に当てる。');
}

/**
 * 【手順2】分割もリトライもせずに一括処理する。6分で強制終了するのが期待動作。
 *
 * 強制終了は catch できない。実行履歴に「タイムアウト」として残るだけで、
 * finally も走らない。つまり「落ちてから片付ける」ことはできず、
 * 落ちる前に自分で止まるしかない ── これが分割実行が必要な理由。
 */
function demoBatchUnsafe() {
  const startedAt = Date.now();
  const sheet = getBatchSheet_();
  const lastRow = sheet.getLastRow();
  let processed = 0;

  for (let row = 2; row <= lastRow; row++) {
    if (String(sheet.getRange(row, 4).getValue() ?? '').trim()) {
      continue;
    }
    // 試行回数1 ＝ リトライなし。429 が来たら即失敗させて、
    // リトライ無しだと何が起きるかを見る。
    processOneBatchRow_(sheet, row, 1);
    processed++;

    if (processed % 10 === 0) {
      console.log(`${processed} 件処理（経過 ${Math.round((Date.now() - startedAt) / 1000)} 秒）`);
    }
  }

  console.log(`全 ${processed} 件を処理し終えた（経過 ${Math.round((Date.now() - startedAt) / 1000)} 秒）。`);
  console.log('6分に届かなかった場合は BATCH_ROW_COUNT を増やして再挑戦する。');
}

/**
 * 【手順3】分割実行とリトライありで処理する。
 * 安全域を超えたら自ら中断し、継続トリガーを張って次回に引き継ぐ。
 */
function demoBatchSafe() {
  PropertiesService.getScriptProperties().deleteProperty(PROP_BATCH_CURSOR);
  demoBatchResume();
}

/**
 * 分割実行の本体。継続トリガーからも呼ばれる。
 *
 * 【設計】再開位置は PropertiesService に保存する。
 * シートの状態列だけでも再開はできるが、毎回先頭から未処理行を探すと
 * 件数が増えるほど走査コストが上がり、そのぶん処理できる件数が減る。
 */
function demoBatchResume() {
  const startedAt = Date.now();
  const props = PropertiesService.getScriptProperties();
  const maxRuntimeMs = Number(props.getProperty(PROP_BATCH_MAX_RUNTIME_MS)) || MAX_RUNTIME_MS;

  // 【重要】自分を呼んだ使い捨てトリガーを最初に削除する。
  // after() のトリガーは実行後も残るため、放置すると溜まり続け、
  // トリガー数の上限（1スクリプト・1ユーザーあたり20個）に当たって
  // 「トリガーを作れない」という別の障害になる。
  deleteBatchTriggers_();

  const sheet = getBatchSheet_();
  const lastRow = sheet.getLastRow();
  const startRow = Number(props.getProperty(PROP_BATCH_CURSOR) || 2);

  let processed = 0;
  let row = startRow;

  for (; row <= lastRow; row++) {
    // 安全域を超えたら、処理を続けずに中断する。
    // 「あと1件くらい」で続けると、その1件がリトライを挟んだ瞬間に強制終了される。
    if (Date.now() - startedAt > maxRuntimeMs) {
      props.setProperty(PROP_BATCH_CURSOR, String(row));
      scheduleBatchResume_();
      console.log(
        `安全域 ${Math.round(maxRuntimeMs / 1000)} 秒に達したため中断した。` +
        `${processed} 件処理、次は行 ${row} から再開する。`
      );
      return;
    }

    if (String(sheet.getRange(row, 4).getValue() ?? '').trim()) {
      continue;
    }

    // 試行回数は既定（RETRY_MAX_ATTEMPTS）。429/5xx は指数バックオフで再試行する。
    processOneBatchRow_(sheet, row);
    processed++;
  }

  props.deleteProperty(PROP_BATCH_CURSOR);
  console.log(`完了。この実行で ${processed} 件処理した（経過 ${Math.round((Date.now() - startedAt) / 1000)} 秒）。`);
}

/**
 * 1行を分類してシートに書く。
 * @param {GoogleAppsScript.Spreadsheet.Sheet} sheet バッチシート
 * @param {number} row 対象行
 * @param {number} [maxAttempts] 最大試行回数
 */
function processOneBatchRow_(sheet, row, maxAttempts) {
  const body = String(sheet.getRange(row, 2).getValue() ?? '');
  try {
    const result = classifyInquiry(body, maxAttempts);
    sheet.getRange(row, 3).setValue(result.category);
    sheet.getRange(row, 4).setValue(STATUS.DONE);
  } catch (error) {
    // 1件の失敗で全体を止めない。失敗を記録して次へ進む。
    // ここで throw すると、残り全件が未処理のまま止まる。
    sheet.getRange(row, 3).setValue('');
    sheet.getRange(row, 4).setValue(`${STATUS.ERROR}: ${error.message.slice(0, 200)}`);
  }
}

/**
 * 【手順4】進捗を確認する。
 */
function demoBatchStatus() {
  const sheet = getBatchSheet_();
  const values = sheet.getRange(2, 4, Math.max(sheet.getLastRow() - 1, 1), 1).getValues();

  const done = values.filter((v) => String(v[0]).trim() === STATUS.DONE).length;
  const failed = values.filter((v) => String(v[0]).startsWith(STATUS.ERROR)).length;
  const pending = values.filter((v) => !String(v[0]).trim()).length;

  const cursor = PropertiesService.getScriptProperties().getProperty(PROP_BATCH_CURSOR);
  const triggers = ScriptApp.getProjectTriggers()
    .filter((t) => t.getHandlerFunction() === BATCH_HANDLER).length;

  console.log(`完了 ${done} / 失敗 ${failed} / 未処理 ${pending}（全 ${values.length} 件）`);
  console.log(`再開カーソル: ${cursor || 'なし（未開始または完了）'}`);
  const override = PropertiesService.getScriptProperties().getProperty(PROP_BATCH_MAX_RUNTIME_MS);
  console.log(`安全域: ${override ? `${Math.round(Number(override) / 1000)} 秒（実験用の上書き）` : `${Math.round(MAX_RUNTIME_MS / 1000)} 秒（既定）`}`);
  console.log(`継続トリガー: ${triggers} 個`);

  // 失敗理由を種類ごとに数える。429 が多いのか、別の原因かを見分ける。
  const reasons = new Map();
  values.forEach(([v]) => {
    const text = String(v);
    if (!text.startsWith(STATUS.ERROR)) {
      return;
    }
    const key = (text.match(/ステータス (\d+)/) || [, 'その他'])[1];
    reasons.set(key, (reasons.get(key) ?? 0) + 1);
  });
  if (reasons.size > 0) {
    console.log(`失敗の内訳: ${[...reasons.entries()].map(([k, n]) => `${k}:${n}件`).join(', ')}`);
  }
}

/**
 * 【必ず実行】継続トリガーを削除して実験を止める。
 */
function demoBatchStop() {
  const removed = deleteBatchTriggers_();
  const props = PropertiesService.getScriptProperties();
  props.deleteProperty(PROP_BATCH_CURSOR);
  // 実験用の上書きも消す。残したまま忘れると、次の実験で意図しない安全域が効く。
  props.deleteProperty(PROP_BATCH_MAX_RUNTIME_MS);
  console.log(`継続トリガーを ${removed} 個削除し、カーソルと安全域の上書きを消した。`);
}

/**
 * 【手順3の前に実行】実験用に安全域を120秒へ短縮する。
 * 残件が少なくても中断・再開が発動するようにするため。
 */
function demoBatchUseShortDeadline() {
  PropertiesService.getScriptProperties().setProperty(PROP_BATCH_MAX_RUNTIME_MS, String(120 * 1000));
  console.log('安全域を 120 秒に短縮した。demoBatchStop で元に戻る。');
}

/**
 * 次回の実行を予約する。
 */
function scheduleBatchResume_() {
  // 1分後に1回だけ走るトリガー。連続実行の間隔を空けるのは、
  // レート制限が回復する時間を稼ぐ意味もある。
  ScriptApp.newTrigger(BATCH_HANDLER).timeBased().after(60 * 1000).create();
}

/**
 * 継続トリガーを全て削除する。
 * @returns {number} 削除した個数
 */
function deleteBatchTriggers_() {
  return ScriptApp.getProjectTriggers()
    .filter((t) => t.getHandlerFunction() === BATCH_HANDLER)
    .map((t) => {
      ScriptApp.deleteTrigger(t);
      return 1;
    }).length;
}

/**
 * バッチシートを取得する。
 * @returns {GoogleAppsScript.Spreadsheet.Sheet} バッチシート
 */
function getBatchSheet_() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_BATCH);
  if (!sheet) {
    throw new Error(`${SHEET_BATCH} シートがありません。demoBatchSetup を実行してください。`);
  }
  return sheet;
}
