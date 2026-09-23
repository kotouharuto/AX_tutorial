/**
 * A-1 ステップ③：分類（Gemini API）
 *
 * 【A-1 の勘所】分類は JSON で返させて JSON.parse() する。
 * 自然文で返させると表記ゆれで必ず壊れる。
 * プロンプトで「JSONのみ出力」と縛った上で、それでも壊れる前提の処理を入れる。
 */

/**
 * 問い合わせ内容を分類する。
 * @param {string} inquiry 問い合わせ本文
 * @param {number} [maxAttempts] 最大試行回数。省略時は RETRY_MAX_ATTEMPTS
 * @returns {{category: string, urgency: string, reason: string}} 分類結果
 * @throws {Error} API 呼び出しまたはパースに失敗した場合
 */
function classifyInquiry(inquiry, maxAttempts) {
  const raw = callGemini_(buildClassificationPrompt_(inquiry), maxAttempts);
  const parsed = parseJsonLoosely_(raw);
  return validateClassification_(parsed);
}

/**
 * 分類プロンプトを組み立てる。
 * @param {string} inquiry 問い合わせ本文
 * @returns {string} プロンプト
 */
function buildClassificationPrompt_(inquiry) {
  return [
    'あなたは社内問い合わせの振り分け担当です。以下の問い合わせを分類してください。',
    '',
    `分類は次のいずれか1つ：${CATEGORIES.join(' / ')}`,
    `緊急度は次のいずれか1つ：${URGENCIES.join(' / ')}`,
    '',
    '出力は JSON のみ。前置き・説明・コードフェンスを一切含めないこと。',
    '形式：{"category": "...", "urgency": "...", "reason": "30字以内の判断理由"}',
    '',
    '--- 問い合わせ ---',
    inquiry,
  ].join('\n');
}

/**
 * Gemini API を呼び、生成されたテキストを返す。
 * @param {string} prompt プロンプト
 * @param {number} [maxAttempts] 最大試行回数。省略時は RETRY_MAX_ATTEMPTS
 * @returns {string} 生成テキスト
 * @throws {Error} キー未設定・回復不能なエラー・試行回数超過の場合
 */
function callGemini_(prompt, maxAttempts) {
  const apiKey = PropertiesService.getScriptProperties().getProperty(PROP_GEMINI_API_KEY);
  if (!apiKey) {
    throw new Error(
      `スクリプトプロパティ ${PROP_GEMINI_API_KEY} が未設定です。` +
      '「プロジェクトの設定 → スクリプト プロパティ」で設定してください。'
    );
  }

  const options = {
    method: 'post',
    contentType: 'application/json',
    // APIキーはクエリ文字列ではなくヘッダで渡す。
    // URL に載せると実行ログやエラーメッセージに残り、鍵が漏れる経路になる。
    headers: { 'x-goog-api-key': apiKey },
    payload: JSON.stringify({
      contents: [{ parts: [{ text: prompt }] }],
      generationConfig: {
        // JSON で返させる。これで壊れる確率は下がるが、ゼロにはならない。
        responseMimeType: 'application/json',
        // 分類は再現性が要るので温度は下げる。
        temperature: 0,
      },
    }),
    // 例外を投げさせず、ステータスコードで分岐する。
    // これを付けないと 4xx/5xx で即例外になり、内容を読んで判断できない。
    muteHttpExceptions: true,
  };

  const response = fetchWithRetry_(GEMINI_ENDPOINT, options, maxAttempts);
  return extractGeneratedText_(response.getContentText());
}

/**
 * 一時障害を指数バックオフで再試行しながら HTTP リクエストを行う。
 *
 * 【fetchFn を差し替え可能にしている理由】
 * 429 や 503 は狙って起こせない（今回の実験でも150件処理して一度も出なかった）。
 * 実際に起きないものを「実装した」で済ませると、いざ起きたときに初めて
 * バグが分かる。スタブを注入して、リトライが作動する証跡を取れるようにする。
 *
 * @param {string} url リクエスト先
 * @param {Object} options UrlFetchApp のオプション
 * @param {number} [maxAttempts] 最大試行回数。省略時は RETRY_MAX_ATTEMPTS
 * @param {Function} [fetchFn] fetch の実装。省略時は UrlFetchApp.fetch
 * @returns {Object} ステータス200のレスポンス
 * @throws {Error} 回復不能なエラー、または試行回数を使い切った場合
 */
function fetchWithRetry_(url, options, maxAttempts, fetchFn) {
  const attempts = maxAttempts === undefined ? RETRY_MAX_ATTEMPTS : maxAttempts;
  const doFetch = fetchFn || ((u, o) => UrlFetchApp.fetch(u, o));

  let lastError = null;
  for (let attempt = 1; attempt <= attempts; attempt++) {
    const response = doFetch(url, options);
    const status = response.getResponseCode();

    if (status === 200) {
      return response;
    }

    const detail =
      `ステータス ${status}（試行 ${attempt}/${attempts}）: ` +
      // 200字では API 側の指示（代替モデル名など）が途中で切れて読めなかったため広げる。
      // API キーはヘッダで送っており本文には含まれないので、この長さでも漏洩しない。
      `${response.getContentText().slice(0, 600)}`;

    if (!isRetryableStatus_(status)) {
      // 400/401/403/404 はこちらの誤り。再試行しても直らないので即座に諦める。
      // ここで粘るとクォータを浪費した上で同じ失敗を積み上げるだけ。
      throw new Error(`回復不能なエラーが返りました。${detail}`);
    }

    lastError = new Error(`一時エラーが返りました。${detail}`);
    if (attempt < attempts) {
      const waitMs = backoffMs_(attempt);
      console.warn(`${waitMs}ms 待って再試行する。${detail}`);
      Utilities.sleep(waitMs);
    }
  }

  // 試行回数を使い切った。ここで必ず諦める。
  // GAS には日次クォータがあるため、無限リトライは書かない。
  throw lastError;
}

/**
 * 再試行する価値があるステータスかを判定する。
 * @param {number} status HTTP ステータスコード
 * @returns {boolean} 再試行すべきなら true
 */
function isRetryableStatus_(status) {
  // 429: レート制限、5xx: サーバ側の一時障害。時間を空ければ回復しうる。
  return status === 429 || (status >= 500 && status < 600);
}

/**
 * 指数バックオフの待機時間を返す。
 * @param {number} attempt 何回目の試行か（1始まり）
 * @returns {number} 待機ミリ秒
 */
function backoffMs_(attempt) {
  const base = RETRY_BASE_MS * Math.pow(2, attempt - 1);
  // ジッターを必ず入れる。複数の実行が同時に失敗した場合、
  // 待機時間が揃っていると再試行のタイミングも揃い、また同時に叩いて再び 429 になる。
  // ランダムにずらすことで再衝突を避ける。
  return Math.round(base * (0.5 + Math.random()));
}

/**
 * 応答本文から生成テキストを取り出す。
 * @param {string} responseText 応答本文（JSON文字列）
 * @returns {string} 生成テキスト
 * @throws {Error} 本文が取り出せない場合
 */
function extractGeneratedText_(responseText) {
  const body = JSON.parse(responseText);
  const text = body?.candidates?.[0]?.content?.parts?.[0]?.text;
  if (!text) {
    // 安全フィルタでブロックされた場合など、200 でも本文が無いことがある。
    // ここを握り潰すと「なぜか未分類になる」という調査困難な状態になる。
    throw new Error(
      `Gemini API の応答に本文がありません。finishReason=${body?.candidates?.[0]?.finishReason}`
    );
  }
  return text;
}

/**
 * JSON をできる限り読み取る。
 *
 * responseMimeType で JSON を指定していても、コードフェンスや前置きが混ざることがある。
 * 「縛った上で、それでも壊れる前提の処理を入れる」ための関数。
 * @param {string} raw モデルの生出力
 * @returns {Object} パース結果
 * @throws {Error} フォールバックしてもパースできない場合
 */
function parseJsonLoosely_(raw) {
  try {
    return JSON.parse(raw);
  } catch (e) {
    // フォールバック1：コードフェンスを剥がす
    const unfenced = raw.replace(/^\s*```(?:json)?\s*/i, '').replace(/\s*```\s*$/, '');
    try {
      return JSON.parse(unfenced);
    } catch (e2) {
      // フォールバック2：最初の { から最後の } までを取り出す（前置き・後置き対策）
      const start = unfenced.indexOf('{');
      const end = unfenced.lastIndexOf('}');
      if (start !== -1 && end > start) {
        try {
          return JSON.parse(unfenced.slice(start, end + 1));
        } catch (e3) {
          // 握り潰さず、下の throw に落とす
        }
      }
      // ここまで来たら諦める。生出力を残すのは、後で何が返ってきたか追えるようにするため。
      throw new Error(`分類結果を JSON として解釈できません: ${raw.slice(0, 200)}`);
    }
  }
}

/**
 * 分類結果が定義済みの値かを検証する。
 *
 * モデルは「システム障害等」「緊急」など、定義にない値を平気で返す。
 * 検証せずにシートへ書くと、担当マスタと突き合わない値が混入して振り分けが黙って失敗する。
 * @param {Object} parsed パース済みオブジェクト
 * @returns {{category: string, urgency: string, reason: string}} 検証済みの分類結果
 * @throws {Error} 定義外の値が含まれる場合
 */
function validateClassification_(parsed) {
  const category = String(parsed?.category ?? '').trim();
  const urgency = String(parsed?.urgency ?? '').trim();

  if (!CATEGORIES.includes(category)) {
    throw new Error(`分類が定義外です: "${category}"（許可: ${CATEGORIES.join('/')}）`);
  }
  if (!URGENCIES.includes(urgency)) {
    throw new Error(`緊急度が定義外です: "${urgency}"（許可: ${URGENCIES.join('/')}）`);
  }

  return {
    category,
    urgency,
    reason: String(parsed?.reason ?? '').trim(),
  };
}
