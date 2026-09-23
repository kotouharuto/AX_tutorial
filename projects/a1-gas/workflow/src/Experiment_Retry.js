/**
 * A-1 ステップ④-3：リトライが実際に作動する証跡を取る
 *
 * 【なぜスタブを使うか】
 * 429 も 503 も狙って起こせない。150件の実測でも一度も出なかった。
 * 「実装した」で済ませると、いざ本番で起きたときに初めてバグが分かる。
 *
 * 多重起動の実験で得た原則をここにも適用する：
 * **対策の検証では、症状が消えたことではなく、対策が働いた証跡を見る。**
 *
 * 【エントリポイント】verifyRetryAll を実行すれば4件まとめて検証できる。
 */

/**
 * 【手順】4つの検証をまとめて実行する。
 */
function verifyRetryAll() {
  verifyRetryRecoversFromTransient();
  verifyRetryStopsOnClientError();
  verifyRetryGivesUp();
  verifyBackoffJitter();
  console.log('--- 検証終了 ---');
}

/**
 * 検証1：一時エラーのあと回復する。
 * 503 → 429 → 200 の順に返し、3回目で成功することを確認する。
 */
function verifyRetryRecoversFromTransient() {
  const stub = makeSequenceFetch_([503, 429, 200]);
  const startedAt = Date.now();

  const response = fetchWithRetry_('https://example.test', {}, 4, stub.fetch);

  const elapsed = Date.now() - startedAt;
  const ok = response.getResponseCode() === 200 && stub.calls() === 3;
  console.log(
    `[検証1] 一時エラーから回復: ${ok ? 'OK' : 'NG'} ` +
    `／ 呼び出し ${stub.calls()} 回・所要 ${elapsed}ms`
  );
  // 所要時間がバックオフの実測値になる。1回目後に約0.5〜1.5秒、2回目後に約1〜3秒待つ。
  console.log(`  → 待機の合計は約 ${elapsed}ms。指数的に伸びていることをログの warn 行で確認する。`);
}

/**
 * 検証2：クライアント起因のエラーでは再試行しない。
 * 401 は何度投げても直らないので、1回で諦めるのが正しい。
 */
function verifyRetryStopsOnClientError() {
  const stub = makeSequenceFetch_([401, 200]);

  let threw = false;
  try {
    fetchWithRetry_('https://example.test', {}, 4, stub.fetch);
  } catch (e) {
    threw = true;
  }

  // 呼び出しが1回で止まっていることが「リトライしていない」証跡。
  const ok = threw && stub.calls() === 1;
  console.log(`[検証2] 4xx で即諦める: ${ok ? 'OK' : 'NG'} ／ 呼び出し ${stub.calls()} 回`);
  console.log('  → ここが2回以上なら、直らないエラーでクォータを浪費している。');
}

/**
 * 検証3：試行回数を使い切ったら諦める。
 * 無限リトライを書いていないことの確認。
 */
function verifyRetryGivesUp() {
  const stub = makeSequenceFetch_([503, 503, 503, 503, 503, 503]);
  const maxAttempts = 3;

  let message = '';
  try {
    fetchWithRetry_('https://example.test', {}, maxAttempts, stub.fetch);
  } catch (e) {
    message = e.message;
  }

  const ok = stub.calls() === maxAttempts && message.indexOf('一時エラー') !== -1;
  console.log(
    `[検証3] 上限で諦める: ${ok ? 'OK' : 'NG'} ` +
    `／ 呼び出し ${stub.calls()} 回（上限 ${maxAttempts}）`
  );
  console.log('  → GAS には日次クォータがあるため、諦める条件は必須。');
}

/**
 * 検証4：バックオフが指数的に伸び、かつジッターで散らばる。
 */
function verifyBackoffJitter() {
  for (let attempt = 1; attempt <= 4; attempt++) {
    const samples = [];
    for (let i = 0; i < 5; i++) {
      samples.push(backoffMs_(attempt));
    }
    const min = Math.min(...samples);
    const max = Math.max(...samples);
    console.log(`[検証4] ${attempt}回目の待機: ${samples.join(', ')} ms（幅 ${min}〜${max}）`);
  }
  console.log('  → 同じ試行回数でも値が散っていること（ジッター）を確認する。');
  console.log('  → 揃っていると、同時に失敗した実行が同時に再試行して再び衝突する。');
}

/**
 * 指定した順にステータスを返すスタブ fetch を作る。
 * @param {number[]} statuses 返すステータスコードの並び
 * @returns {{fetch: Function, calls: Function}} スタブと呼び出し回数の取得関数
 */
function makeSequenceFetch_(statuses) {
  let index = 0;
  return {
    fetch: () => {
      // 並びを超えたら最後の値を返し続ける（呼びすぎても落ちないようにする）
      const status = statuses[Math.min(index, statuses.length - 1)];
      index++;
      return makeStubResponse_(status);
    },
    calls: () => index,
  };
}

/**
 * UrlFetchApp のレスポンスに見せかけたスタブを作る。
 * fetchWithRetry_ が使うのは getResponseCode と getContentText だけなので、
 * この2つだけ実装すれば足りる。
 * @param {number} status ステータスコード
 * @returns {{getResponseCode: Function, getContentText: Function}} スタブレスポンス
 */
function makeStubResponse_(status) {
  const body = status === 200
    ? JSON.stringify({ candidates: [{ content: { parts: [{ text: '{"category":"その他"}' }] } }] })
    : JSON.stringify({ error: { code: status, message: `stub error ${status}` } });
  return {
    getResponseCode: () => status,
    getContentText: () => body,
  };
}
