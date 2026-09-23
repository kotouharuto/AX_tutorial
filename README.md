# AX 副業 — Phase A 作業リポジトリ

AXコンサル副業に向けた **Phase A（技術習得）** の検証・記録用リポジトリ。
Phase B（事業化：契約・集客・価格・営業）は**対象外**。

## 入口

| 見たいもの | ファイル |
|---|---|
| **Phase A で何をやり、何が分かったか** | **[docs/phase-a-summary.md](docs/phase-a-summary.md)** |
| **Phase B への引き継ぎ**（チャットに貼って使う） | **[docs/phase-b-handover.md](docs/phase-b-handover.md)** |
| 全体方針・ブロック構成 | [docs/00-roadmap.md](docs/00-roadmap.md) |
| いまどこまで進んだか | [docs/progress.md](docs/progress.md) |
| 次に何をどう進めるか | [docs/process/](docs/process/) |
| 踏んだ落とし穴 | [docs/pitfalls/README.md](docs/pitfalls/README.md) |
| 何にどれだけ時間がかかったか | [docs/logs/](docs/logs/) |
| AIエージェント向けの運用ルール | [CLAUDE.md](CLAUDE.md) |

## ブロック

| # | ブロック | 目的 | 目安 | 状態 |
|---|---|---|---|---|
| A-1 | [GAS と業務システム接続](docs/process/10-A1-gas.md) | 成果物を実際の業務に着地させる | 2〜3週 | **完了 7/7** |
| A-2 | [RAG と評価設計](docs/process/20-A2-rag.md) | 「情報が散らばっている」問題に応える | 2〜4週 | **完了 6/6** |
| A-3 | [他人が使い続ける形にする](docs/process/30-A3-handover.md) | 引き渡し後に動き続ける設計 | 2〜3週 | **5/6**（条件6は協力者不在で未達） |

**期間ではなく到達条件で管理する。** 目安期間は締切ではなく、大きく超えたときに
深入りを疑うための基準。

## 現在地

**Phase A 区切り**（2026-09-23）。実作業 約25時間、ハマりポイント 27件。
→ [docs/phase-a-summary.md](docs/phase-a-summary.md)

## 運用の約束

1. 完了条件を満たしたら [docs/progress.md](docs/progress.md) にチェックを入れる
2. 詰まって解決したら [docs/pitfalls/](docs/pitfalls/) に1件足す（**原因と対処をセットで**）
3. セッション終了時に [docs/logs/](docs/logs/) へ実測時間を書く
4. 認証情報・APIキー・実データはコミットしない
