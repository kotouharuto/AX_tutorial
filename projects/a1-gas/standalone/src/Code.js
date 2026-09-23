/**
 * A-1 ステップ⑤：配置パターンの比較（スタンドアロン版）
 *
 * projects/a1-gas/minimal と**処理内容は同一**で、配置だけを変えたもの。
 * 目的は機能ではなく、コンテナバインドとの差分を実物で確認すること。
 *
 * 【最大の差分：スコープ】
 *   コンテナバインド版: spreadsheets.currentonly（このシートのみ）
 *   スタンドアロン版  : spreadsheets（**全スプレッドシート**）
 *
 * スタンドアロンには「このシート」という概念がない。
 * SpreadsheetApp.getActiveSpreadsheet() は null を返す。
 * openById() で開く必要があり、そのために全スプレッドシートへの権限を要求することになる。
 *
 * 処理内容が同じでも、配置を変えるだけで要求権限が広がる。
 */

/** 読み取り対象のセル。minimal 版と揃える。 */
const SOURCE_CELL = 'A2';

/** 対象スプレッドシートの ID を格納するキー。 */
const PROP_TARGET_SPREADSHEET_ID = 'TARGET_SPREADSHEET_ID';

/** 宛先を格納するキー。 */
const PROP_NOTIFY_TO = 'NOTIFY_TO';

/**
 * 【エントリポイント】シートを1行読んで、Gmail を1通送る。
 * minimal 版の sendMinimalNotification と同じことをする。
 */
function sendMinimalNotification() {
  const to = getRequiredProperty_(PROP_NOTIFY_TO);
  const sheet = openTargetSheet_();
  const value = sheet.getRange(SOURCE_CELL).getDisplayValue();

  const body = value
    ? `シートの ${SOURCE_CELL} の値：${value}`
    : `シートの ${SOURCE_CELL} は空でした。`;

  GmailApp.sendEmail(to, '[A1-standalone] スタンドアロンからの疎通確認', body);
  console.log(`送信完了。読み取り値の有無: ${value ? 'あり' : 'なし'}`);
}

/**
 * 【診断用】配置パターンの差分を実際に確認する。
 * getActiveSpreadsheet() が使えないことを、目で見て確かめるための関数。
 */
function checkPlacementDifference() {
  // コンテナバインドなら現在のスプレッドシートが返るが、
  // スタンドアロンには「現在の」という概念が無いため null になる。
  const active = SpreadsheetApp.getActiveSpreadsheet();
  console.log(`getActiveSpreadsheet(): ${active ? active.getName() : 'null（スタンドアロンなので取得できない）'}`);

  const id = PropertiesService.getScriptProperties().getProperty(PROP_TARGET_SPREADSHEET_ID);
  console.log(`${PROP_TARGET_SPREADSHEET_ID}: ${id ? '設定あり' : '未設定'}`);
  console.log(`${PROP_NOTIFY_TO}: ${PropertiesService.getScriptProperties().getProperty(PROP_NOTIFY_TO) ? '設定あり' : '未設定'}`);

  if (!id) {
    console.log('対象シートIDを設定すると、openById での読み取りまで確認できる。');
    return;
  }

  const sheet = openTargetSheet_();
  console.log(`openById で開いたシート: ${sheet.getParent().getName()} / ${sheet.getName()}`);
  console.log(`${SOURCE_CELL} の値: "${sheet.getRange(SOURCE_CELL).getDisplayValue()}"`);
  console.log('→ 同じ読み取りをするのに、必要なスコープが currentonly から spreadsheets に広がっている。');
}

/**
 * 対象スプレッドシートの先頭シートを開く。
 *
 * openById は「ID を知っていれば、そのユーザーがアクセスできる任意のシートを開ける」。
 * だから spreadsheets（全スプレッドシート）スコープが必要になる。
 * currentonly のように「このファイルだけ」と限定する手段がない。
 * @returns {GoogleAppsScript.Spreadsheet.Sheet} 対象シート
 */
function openTargetSheet_() {
  const id = getRequiredProperty_(PROP_TARGET_SPREADSHEET_ID);
  return SpreadsheetApp.openById(id).getSheets()[0];
}

/**
 * 必須プロパティを取得する。未設定なら明示的に失敗させる。
 * @param {string} key プロパティキー
 * @returns {string} 値
 */
function getRequiredProperty_(key) {
  const value = PropertiesService.getScriptProperties().getProperty(key);
  if (!value) {
    throw new Error(
      `スクリプトプロパティ ${key} が未設定です。` +
      '「プロジェクトの設定 → スクリプト プロパティ」で設定してください。'
    );
  }
  return value;
}
