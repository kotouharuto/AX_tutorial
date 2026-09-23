/**
 * A-1 ステップ④-2：トリガー多重起動を意図的に起こす実験
 *
 * 【目的】うまく動かすことではなく、二重処理を実際に発生させること。
 * 先に事故らせてから対処を入れる。
 *
 * 【本番と分ける理由】フォーム回答シートで起こすと実際にメールが二重送信され、
 * ステップ③の失敗行とも混ざって観察しづらい。専用シートで起こす。
 *
 * 【分類をスタブにする理由】観察対象は競合であって API ではない。
 * Gemini を呼ぶと遅延と失敗という変数が増え、二重処理が原因なのか
 * API 起因なのか切り分けられなくなる。代わりに sleep で競合ウィンドウを広げる。
 */

/** 実験用シート */
const SHEET_DEMO = '多重起動デモ';
const SHEET_EXEC_LOG = '実行ログ';

/** 排他制御の有無を切り替えるフラグ。'true' で LockService を使う。 */
const PROP_DEMO_SAFE_MODE = 'DEMO_SAFE_MODE';

/** 1行あたりの疑似処理時間（ミリ秒）。競合を観測可能にするために入れている。 */
const DEMO_WORK_MS = 2000;

/** 実験用の行数。1分トリガーの間隔をまたぐ長さにする。 */
const DEMO_ROW_COUNT = 20;

/**
 * 【手順1】実験用シートを用意し、未処理行を投入する。
 * 何度実行しても作り直す（実験のたびに初期化したいため、あえて冪等にしない）。
 */
function demoSetup() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  const demo = recreateSheet_(ss, SHEET_DEMO);
  demo.getRange(1, 1, 1, 3).setValues([['ID', '内容', '状態']]);
  const rows = [];
  for (let i = 1; i <= DEMO_ROW_COUNT; i++) {
    rows.push([`R${String(i).padStart(3, '0')}`, `ダミー問い合わせ ${i}`, '']);
  }
  demo.getRange(2, 1, rows.length, 3).setValues(rows);
  demo.setFrozenRows(1);

  const log = recreateSheet_(ss, SHEET_EXEC_LOG);
  log.getRange(1, 1, 1, 4).setValues([['時刻', '実行ID', '対象ID', '動作']]);
  log.setFrozenRows(1);

  console.log(`${SHEET_DEMO} に ${DEMO_ROW_COUNT} 行の未処理データを投入した。`);
  console.log('次に demoStartUnsafe を実行して、排他なしで多重起動させる。');
}

/**
 * 【手順2】排他制御なしで多重起動させる。
 * 1分間隔のトリガーを2本登録し、同じ処理を並行させる。
 */
function demoStartUnsafe() {
  PropertiesService.getScriptProperties().setProperty(PROP_DEMO_SAFE_MODE, 'false');
  startDemoTriggers_();
  console.log('排他なしで起動した。1〜3分待ってから demoShowResult を実行すること。');
}

/**
 * 【手順4】排他制御ありで多重起動させる。手順1（demoSetup）でリセットしてから使う。
 */
function demoStartSafe() {
  PropertiesService.getScriptProperties().setProperty(PROP_DEMO_SAFE_MODE, 'true');
  startDemoTriggers_();
  console.log('排他ありで起動した。1〜3分待ってから demoShowResult を実行すること。');
}

/**
 * 【必ず実行】実験用トリガーを全て削除する。
 *
 * 消し忘れると1分ごとに動き続け、実行回数のクォータを消費し続ける。
 * 「作った人がいなくなっても動き続ける」ものを作ってしまう典型なので、
 * 停止手段を最初から用意しておく。
 */
function demoStop() {
  const removed = ScriptApp.getProjectTriggers()
    .filter((t) => t.getHandlerFunction() === 'demoProcessPending')
    .map((t) => {
      ScriptApp.deleteTrigger(t);
      return 1;
    }).length;
  console.log(`実験用トリガーを ${removed} 個削除した。`);
}

/**
 * 【手順3】結果を集計し、二重処理が起きたかを判定する。
 */
function demoShowResult() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const log = ss.getSheetByName(SHEET_EXEC_LOG);
  if (!log || log.getLastRow() < 2) {
    console.log('実行ログがまだありません。トリガーの起動を待ってください。');
    return;
  }

  const rows = log.getRange(2, 1, log.getLastRow() - 1, 4).getValues();
  const processed = rows.filter((r) => r[3] === '処理');

  // 対象IDごとの処理回数を数える。2回以上あれば二重処理。
  const counts = new Map();
  processed.forEach(([, , id]) => counts.set(id, (counts.get(id) ?? 0) + 1));
  const duplicated = [...counts.entries()].filter(([, n]) => n > 1);

  const executions = new Set(rows.map((r) => r[1]));
  const skippedByLock = rows.filter((r) => r[3] === 'ロック取得失敗').length;

  console.log(`実行回数: ${executions.size}`);
  console.log(`処理件数: ${processed.length}（対象は ${DEMO_ROW_COUNT} 件）`);
  console.log(`ロックで見送った実行: ${skippedByLock}`);
  console.log(`二重処理された対象: ${duplicated.length} 件`);
  if (duplicated.length > 0) {
    console.log(`  例: ${duplicated.slice(0, 5).map(([id, n]) => `${id}(${n}回)`).join(', ')}`);
  }
}

/**
 * トリガーから呼ばれる本体。排他の有無をプロパティで切り替える。
 * 切り替え式にしているのは、同じ処理で「あり／なし」を比較するため。
 */
function demoProcessPending() {
  const safe =
    PropertiesService.getScriptProperties().getProperty(PROP_DEMO_SAFE_MODE) === 'true';

  // 実行ごとの識別子。どの実行がどの行を処理したかを追うために使う。
  const executionId = Utilities.getUuid().slice(0, 8);

  if (!safe) {
    // 【排他なし】そのまま処理する。並行実行されれば同じ行を2回処理する。
    processDemoRows_(executionId);
    return;
  }

  // 【排他あり】スクリプト単位のロックを取る。
  const lock = LockService.getScriptLock();
  // tryLock(0) で即座に諦める。waitLock で待たせないのは、
  // 定期実行では「前の実行が動いているなら今回は何もしない」で十分だから。
  // 待たせると実行が積み上がり、6分制限に当たる原因になる。
  if (!lock.tryLock(0)) {
    appendExecLog_(executionId, '-', 'ロック取得失敗');
    console.log('他の実行が処理中のため、今回は何もしない。');
    return;
  }
  try {
    processDemoRows_(executionId);
  } finally {
    // finally で必ず解放する。例外時に解放し忘れると、
    // ロックが残って以降の実行が全て空振りする。
    lock.releaseLock();
  }
}

/**
 * 未処理行を処理する。
 * @param {string} executionId 実行識別子
 */
function processDemoRows_(executionId) {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_DEMO);
  if (!sheet) {
    throw new Error(`${SHEET_DEMO} シートがありません。demoSetup を実行してください。`);
  }

  const lastRow = sheet.getLastRow();
  for (let row = 2; row <= lastRow; row++) {
    const id = String(sheet.getRange(row, 1).getValue());
    const status = String(sheet.getRange(row, 3).getValue() ?? '').trim();

    // 【ここが競合の核心】状態を読んでから書くまでに隙間がある。
    // 排他がなければ、別の実行も同じ瞬間に「空」を読み、両方が処理に進む。
    // フラグ列だけでは同時実行を防げないことの実演。
    if (status) {
      continue;
    }

    // 疑似的な重い処理。実際は API 呼び出しがこの位置に入る。
    Utilities.sleep(DEMO_WORK_MS);

    sheet.getRange(row, 3).setValue(`完了(${executionId})`);
    appendExecLog_(executionId, id, '処理');
  }
}

/**
 * 実行ログに1行追記する。
 * @param {string} executionId 実行識別子
 * @param {string} targetId 対象ID
 * @param {string} action 動作
 */
function appendExecLog_(executionId, targetId, action) {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_EXEC_LOG);
  if (!sheet) {
    return;
  }
  // appendRow は行追加を内部で直列化するため、ログ自体は競合しにくい。
  sheet.appendRow([new Date(), executionId, targetId, action]);
}

/**
 * 実験用トリガーを2本登録する。
 * 同じ関数に複数のトリガーを付けられるため、これで並行実行が起きやすくなる。
 */
function startDemoTriggers_() {
  demoStop(); // 前回の残りを消してから張る
  for (let i = 0; i < 2; i++) {
    ScriptApp.newTrigger('demoProcessPending').timeBased().everyMinutes(1).create();
  }
  console.log('1分間隔のトリガーを2本登録した。実験後は必ず demoStop を実行すること。');
}

/**
 * シートを作り直す。既存があれば削除してから作る。
 * @param {GoogleAppsScript.Spreadsheet.Spreadsheet} ss 対象スプレッドシート
 * @param {string} name シート名
 * @returns {GoogleAppsScript.Spreadsheet.Sheet} 作成したシート
 */
function recreateSheet_(ss, name) {
  const existing = ss.getSheetByName(name);
  if (existing) {
    ss.deleteSheet(existing);
  }
  return ss.insertSheet(name);
}
