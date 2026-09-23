/**
 * A-1 ステップ③：振り分け先の解決（担当マスタの読み込み）
 *
 * 業務ルールをシートに置いた代償として、読み込み時の検証がこちらの責務になる。
 * シートは誰でも編集できる ＝ 空欄・全角スペース・打ち間違いが必ず入る前提で書く。
 */

/**
 * 担当マスタを読み、分類 → 宛先の対応表を返す。
 * 宛先が空・不正な行は除外する（黙って除外せず、呼び出し側で不足を検知できるようにする）。
 * @returns {Map<string, string>} 分類名 → メールアドレス
 * @throws {Error} 担当マスタシートが存在しない場合
 */
function readRoutingTable_() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_ROUTING);
  if (!sheet) {
    throw new Error(`${SHEET_ROUTING} シートがありません。setup を実行してください。`);
  }

  const rows = sheet.getDataRange().getValues().slice(1); // ヘッダ行を除く
  const table = new Map();

  rows.forEach(([category, email]) => {
    const key = String(category ?? '').trim();
    // 全角スペースは trim() で落ちないため明示的に除去する。
    // シート入力では実際に混入する（コピペ由来）。
    const value = String(email ?? '').replace(/[\s　]/g, '');
    if (key && isValidEmail_(value)) {
      table.set(key, value);
    }
  });

  return table;
}

/**
 * メールアドレスとして最低限の形をしているかを判定する。
 * 厳密な検証はしない（RFC 準拠の正規表現は保守できないため）。
 * 目的は「明らかな入力ミスで送信が失敗するのを防ぐ」こと。
 * @param {string} value 検証対象
 * @returns {boolean} 妥当そうなら true
 */
function isValidEmail_(value) {
  return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value);
}

/**
 * 分類に対応する宛先を解決する。
 * 対応がなければフォールバック宛先を返す。
 *
 * 【設計判断】宛先が見つからないときに処理を止めない。
 * 止めると問い合わせが宙に浮き、誰も気づかないまま放置される。
 * 「誰かには必ず届く」方を優先し、フォールバックで受けた事実を記録に残す。
 * @param {string} category 分類名
 * @returns {{to: string, isFallback: boolean}} 宛先と、フォールバックか否か
 * @throws {Error} フォールバック宛先も未設定の場合
 */
function resolveAssignee_(category) {
  const table = readRoutingTable_();
  const to = table.get(category);
  if (to) {
    return { to, isFallback: false };
  }

  const fallback = PropertiesService.getScriptProperties().getProperty(PROP_FALLBACK_TO);
  if (!fallback) {
    throw new Error(
      `分類「${category}」の担当者が ${SHEET_ROUTING} に未設定で、` +
      `フォールバック宛先（${PROP_FALLBACK_TO}）も未設定です。`
    );
  }
  return { to: fallback, isFallback: true };
}
