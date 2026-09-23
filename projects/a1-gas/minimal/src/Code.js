/**
 * A-1 ステップ②：最小の1本
 *
 * スプレッドシートを1行読んで、Gmail を1通送るだけ。
 * 目的は機能ではなく経路の確認（ローカル編集 → clasp push → 実行 → ログ確認）。
 *
 * 宛先はコードに直書きせず、スクリプトプロパティ NOTIFY_TO から読む。
 * 理由は2つ：
 *   1. メールアドレス（個人情報）をリポジトリに含めないため
 *   2. Session.getActiveUser() を使うと userinfo 系スコープが増え、最小権限の原則に反するため
 *
 * 【関数の並び順について】
 * Apps Script エディタは「ファイル内で最初に定義された関数」を実行対象として既定選択する。
 * 補助関数を先頭に置くと、実行ボタンを押しても意図した処理が走らない（承認だけ通って何も起きない）。
 * そのためエントリポイントを必ず先頭に置く。
 */

/** 読み取り対象のセル。最小構成なので固定でよい。 */
const SOURCE_CELL = 'A2';

/** 宛先を格納するスクリプトプロパティのキー。 */
const PROP_NOTIFY_TO = 'NOTIFY_TO';

/**
 * 【エントリポイント】最小の1本：シートを1行読んで、Gmail を1通送る。
 * clasp push 後、Apps Script エディタでこの関数を選んで実行する。
 */
function sendMinimalNotification() {
  const to = getNotifyTo();
  const value = readOneRow();

  // 空セルは「読めなかった」のか「空だった」のか区別がつかないため、明示的に扱う。
  const body = value
    ? `シートの ${SOURCE_CELL} の値：${value}`
    : `シートの ${SOURCE_CELL} は空でした。`;

  GmailApp.sendEmail(to, '[A1-minimal] GAS からの疎通確認', body);

  // 宛先はログに出さない（個人情報をログに残さない方針）。
  console.log(`送信完了。読み取り値の有無: ${value ? 'あり' : 'なし'}`);
}

/**
 * 【診断用】メールを送らずに、実行前提が揃っているかだけを確認する。
 * 「メールが届かない」ときに、どの前提が欠けているかを切り分けるために使う。
 * 実行後、エディタ下部の実行ログを読むこと。
 */
function checkSetup() {
  const props = PropertiesService.getScriptProperties();
  const to = props.getProperty(PROP_NOTIFY_TO);

  // 宛先そのものは個人情報なのでログに出さず、設定の有無と形式だけを報告する。
  console.log(`スクリプトプロパティ ${PROP_NOTIFY_TO}: ${to ? '設定あり' : '未設定'}`);
  if (to) {
    console.log(`宛先の形式: ${to.includes('@') ? '妥当' : '不正（@ を含まない）'}`);
  } else {
    console.log(`設定済みキー一覧: ${JSON.stringify(props.getKeys())}`);
  }

  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  console.log(`シート名: ${sheet.getName()}`);
  console.log(`${SOURCE_CELL} の値: "${sheet.getRange(SOURCE_CELL).getDisplayValue()}"`);

  // 【削除済み】MailApp.getRemainingDailyQuota() は書かない。
  // MailApp は script.send_mail スコープを要求し、GmailApp（gmail.send）とは別物。
  // 診断のためだけに権限を増やさない。
}

/**
 * 宛先を取得する。未設定なら明示的にエラーを投げる（サイレントに握り潰さない）。
 * @returns {string} 通知先メールアドレス
 */
function getNotifyTo() {
  const to = PropertiesService.getScriptProperties().getProperty(PROP_NOTIFY_TO);
  if (!to) {
    throw new Error(
      `スクリプトプロパティ ${PROP_NOTIFY_TO} が未設定です。` +
      'Apps Script エディタの「プロジェクトの設定 → スクリプト プロパティ」で設定してください。'
    );
  }
  return to;
}

/**
 * シートから1行分の値を読み取る。
 * getActiveSpreadsheet() を使うのはコンテナバインドだから。
 * これにより spreadsheets.currentonly（このシートのみ）という最小スコープで済む。
 * スタンドアロン構成では openById() が必要になり、より広い spreadsheets スコープを要求することになる。
 * @returns {string} セルの値（空文字の場合もそのまま返す）
 */
function readOneRow() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  return sheet.getRange(SOURCE_CELL).getDisplayValue();
}
