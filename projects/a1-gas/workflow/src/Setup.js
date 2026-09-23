/**
 * A-1 ステップ③：初期セットアップ
 *
 * 【エントリポイント】Apps Script エディタでこの関数を選んで1回だけ実行する。
 * エディタはファイル内の最初の関数を既定選択するため、エントリポイントを先頭に置く
 * （→ docs/pitfalls/a1-gas-approved-but-nothing-happens.md）。
 *
 * セットアップをコード化するのは、引き渡し時に手順書ではなく実行可能な形で渡すため。
 * 手順書は読まれないが、関数1つなら実行される。
 */
function setup() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  const form = createInquiryForm_(ss);
  ensureRoutingSheet_(ss);
  ensureFormSubmitTrigger_(ss);

  console.log('セットアップ完了。');
  console.log(`フォームURL: ${form.getPublishedUrl()}`);
  console.log('次にスクリプトプロパティ GEMINI_API_KEY と FALLBACK_TO を設定すること。');
}

/**
 * 問い合わせフォームを作成し、回答先をこのスプレッドシートに設定する。
 * @param {GoogleAppsScript.Spreadsheet.Spreadsheet} ss 回答先のスプレッドシート
 * @returns {GoogleAppsScript.Forms.Form} 作成したフォーム
 */
function createInquiryForm_(ss) {
  // 【A-3 で修正】冪等にする。これが無いと setup のたびにフォームが増え、
  // Google Forms が回答先シートを「フォームの回答 N」として分裂させる。
  // 結果、GAS が見ているシートと回答が入るシートがずれて、黙って処理されなくなる。
  const props = PropertiesService.getScriptProperties();
  const existingId = props.getProperty(PROP_FORM_ID);
  if (existingId) {
    try {
      const existing = FormApp.openById(existingId);
      console.log('フォームは作成済みのため何もしない。');
      return existing;
    } catch (e) {
      console.warn(`記録されたフォーム ${existingId} を開けないため、新規作成する。`);
    }
  }

  const form = FormApp.create('社内問い合わせ受付（A1-workflow 検証用）');
  props.setProperty(PROP_FORM_ID, form.getId());

  form.setDescription('※ A-1 検証用の架空フォームです。実データは入力しないでください。');

  // 氏名とメールは振り分けメールの本文に使う。必須にしないと空欄が混ざり、
  // 「想定外の入力」の温床になる（それ自体は A-3 で意図的に踏む）。
  form.addTextItem().setTitle('お名前').setRequired(true);
  form.addTextItem().setTitle('メールアドレス').setRequired(true);
  form.addParagraphTextItem().setTitle('問い合わせ内容').setRequired(true);

  // 回答先をこのスプレッドシートにする。
  // フォームにバインドせずシート側にスクリプトを置くのは、シート操作を
  // currentonly スコープで済ませるため。フォームバインドだと openById が要る。
  form.setDestination(FormApp.DestinationType.SPREADSHEET, ss.getId());

  return form;
}

/**
 * 担当マスタシートを用意する。既にあれば何もしない（冪等）。
 * @param {GoogleAppsScript.Spreadsheet.Spreadsheet} ss 対象スプレッドシート
 */
function ensureRoutingSheet_(ss) {
  const existing = ss.getSheetByName(SHEET_ROUTING);
  if (existing) {
    console.log(`${SHEET_ROUTING} は作成済みのため何もしない。`);
    return;
  }

  const sheet = ss.insertSheet(SHEET_ROUTING);
  sheet.getRange(1, 1, 1, 2).setValues([['分類', '担当者メールアドレス']]);

  // 分類カテゴリの行だけ用意し、宛先は空にしておく。
  // ここを人が埋めるのが「業務ルールをシートで持つ」ということ。
  const rows = CATEGORIES.map((category) => [category, '']);
  sheet.getRange(2, 1, rows.length, 2).setValues(rows);
  sheet.setFrozenRows(1);
}

/**
 * フォーム送信トリガーを登録する。
 * 既に同じトリガーがあれば追加しない。
 *
 * 【重要】ここで重複登録を防いでいるのは、トリガーが二重に登録されると
 * 1回の送信で処理が2回走るため。ステップ④の多重起動はこれとは別に
 * 意図的に起こすが、事故として増殖させないための最低限の防御は入れておく。
 * @param {GoogleAppsScript.Spreadsheet.Spreadsheet} ss 対象スプレッドシート
 */
function ensureFormSubmitTrigger_(ss) {
  const already = ScriptApp.getProjectTriggers().some(
    (t) => t.getHandlerFunction() === 'onFormSubmit'
  );
  if (already) {
    console.log('フォーム送信トリガーは登録済みのため何もしない。');
    return;
  }

  ScriptApp.newTrigger('onFormSubmit')
    .forSpreadsheet(ss)
    .onFormSubmit()
    .create();
  console.log('フォーム送信トリガーを登録した。');
}

/**
 * 【診断用】実行前提が揃っているかを、副作用なしで確認する。
 * 「動かない」ときは原因を1つずつ潰すより、前提を一度に可視化する方が速い。
 */
function checkSetup() {
  const props = PropertiesService.getScriptProperties();
  const keys = props.getKeys();

  // APIキー・メールアドレスは値そのものをログに出さない。有無と形式だけ報告する。
  console.log(`${PROP_GEMINI_API_KEY}: ${props.getProperty(PROP_GEMINI_API_KEY) ? '設定あり' : '未設定'}`);
  console.log(`${PROP_FALLBACK_TO}: ${props.getProperty(PROP_FALLBACK_TO) ? '設定あり' : '未設定'}`);
  console.log(`設定済みキー一覧: ${JSON.stringify(keys)}`);

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  console.log(`シート一覧: ${ss.getSheets().map((s) => s.getName()).join(' / ')}`);

  const routing = ss.getSheetByName(SHEET_ROUTING);
  if (routing) {
    const filled = readRoutingTable_().size;
    console.log(`担当マスタ: ${filled} 件の宛先が設定済み（カテゴリ数 ${CATEGORIES.length}）`);
  } else {
    console.log('担当マスタ: 未作成（setup を実行すること）');
  }

  const triggers = ScriptApp.getProjectTriggers()
    .filter((t) => t.getHandlerFunction() === 'onFormSubmit');
  console.log(`フォーム送信トリガー: ${triggers.length} 個`);

  // 【削除済み】MailApp.getRemainingDailyQuota() はここには書かない。
  // MailApp と GmailApp はスコープが別で、前者は script.send_mail を要求する。
  // 送信自体は GmailApp（gmail.send）で足りるため、診断のためだけに
  // 権限を1つ増やすのは割に合わない。残り送信数は Apps Script のダッシュボードで見る。
}
