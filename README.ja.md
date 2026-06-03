<p align="center">
  <a href="README.md">English</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/mcp-tool-shop-org/prism-verify/main/assets/prism-verify-logo.png" alt="prism-verify logo" width="500">
</p>

<p align="center">
  <a href="https://pypi.org/project/prism-verify/"><img src="https://img.shields.io/pypi/v/prism-verify" alt="PyPI"></a>
  <a href="https://www.npmjs.com/package/@mcptoolshop/prism-verify"><img src="https://img.shields.io/npm/v/@mcptoolshop/prism-verify" alt="npm"></a>
  <a href="https://mcp-tool-shop-org.github.io/prism-verify/"><img src="https://img.shields.io/badge/Landing_Page-live-22d3ee" alt="Landing Page"></a>
  <a href="https://mcp-tool-shop-org.github.io/prism-verify/handbook/"><img src="https://img.shields.io/badge/Handbook-docs-22d3ee" alt="Handbook"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License"></a>
</p>

# 

エージェントのワークフローに対する、実行時の裁定サービス。異なるモデルファミリーを使用し、推論機能を排除した上で、複数のレンズを用いて検証を行い、検証結果を再現可能にします。**[ランディングページとハンドブックはこちら →](https://mcp-tool-shop-org.github.io/prism-verify/)**

## インストール

`prism` CLI（およびHTTPサービス）をPATHに追加してインストールします。

```bash
uv tool install prism-verify        # or: pipx install prism-verify
```

Pythonがインストールされていない場合：npmランチャーを使用します（事前に構築されたバイナリをダウンロードし、SHA256で検証します）。

```bash
npx @mcptoolshop/prism-verify verify --artifact @file.py --intent "..." --caller-family openai
```

または、ライブラリとして追加します。追加オプション：`[anthropic]` `[openai]` `[google]` `[mcp]` `[http]` `[all]`。

```bash
uv add prism-verify
# or
pip install "prism-verify[all]"
```

## クイックスタート

Prismは、常に呼び出し元のモデルとは**異なる**モデルファミリーを使用して検証を行います（ロック1）。そのため、少なくとも1つ以上の代替モデルファミリープロバイダーを設定してください。Ed25519署名キーを生成します（デフォルト設定では、公開キーを持つすべてのユーザーが検証結果を確認できます）。これにより、検証結果を記録したり、ローカル環境でテストするために`PRISM_DEV=1`を使用したりできます。

```bash
prism keygen --out ~/.prism/signing_key.pem      # Ed25519 keypair (default signing)
export PRISM_SIGNING_KEY=~/.prism/signing_key.pem # or: export PRISM_DEV=1 (local play)
export ANTHROPIC_API_KEY="sk-ant-..."             # alt-family verifier for an OpenAI-family caller

prism verify \
  --artifact @myfile.py \
  --intent "Sort a list in O(n log n)" \
  --caller-family openai \
  --provider anthropic
```

> 従来の代替手段：`export PRISM_SIGNING_SECRET="$(openssl rand -hex 32)"` を使用すると、HMACを使用して検証結果に署名します（この共有シークレットを所有しているユーザーのみが検証できます。詳細については、[検証結果](#receipts--signing-ed25519-verifiable-by-anyone)を参照）。

## アーキテクチャ

Prismは、APIコントラクトにおいて、以下の4つのアーキテクチャロックを適用します。

1. **異なるモデルファミリーの使用**：呼び出し元のモデルファミリーは、検証から常に除外されます。
2. **推論の排除**：異なるモデルファミリー間でデータをやり取りする前に、プロデューサーのCoT（Chain of Thought）を削除します。
3. **複数の検証手法の適用**：少なくとも3つの独立した検証手法を並行して実行します。
4. **準単調性の考慮**：検証手法の結果が過度に一致する場合（信号の崩壊）、検証を拒否します。

**引用**に関する検証においては、LLMの根拠性チェックの前に、段階的な検証層が設けられます。各段階では、証明できることのみを受け入れ、それ以外は却下します。

- **存在検証層** — 実際のarXiv/Crossrefからの情報取得を行います。捏造された識別子は破棄され、検証の対象とはなりません。
- **数値/単位検証層** — パーセンテージの入れ替え、単位スケールのずれ（42ミリ秒 vs マイクロ秒）、または比較方向の誤り（5.0 < 5.8 ≠ 「超過」）などが算術的に検出されます。
- **根拠性チェック** — 取得した概要に対して、異なるモデルファミリーの、推論能力を剥奪したLLMによるチェックを行います。
- **直交NLI検証層** *(オプション、`PRISM_NLI_FLOOR`)* — エンコーダーNLIクロスエンコーダーが、LLMが「支持」したものの、メカニズムが異なる別のモデルでは裏付けられない場合に、その結果を却下します。

## キャリブレーションとベンチマーク（`prism eval`）

Prismは、単に結果を表明するだけでなく、**測定**できるように設計されています。`prism eval`は、ラベル付けされたコーパスに対して複数のレンズを適用し、Prism自身のデータに基づいて、各レンズの精度/再現率/MCC、レンズ間の多様性マトリックス（Krippendorff α + ペアごとのCohen κ）、サブモジュールカバレッジの改善、判断の正確性、および信頼性キャリブレーション（ECE/Brier）を報告します。それぞれの結果には、信頼できる信頼区間が含まれます。

```bash
prism eval --split public --runs 3     # measure against the bundled corpus (needs a verifier)
prism eval --offline                    # deterministic mock (CI smoke; NOT a real measurement)
```

v0.5の実行（ローカルの`mistral-small:24b`）により、主要なロックにおける明確なギャップが明らかになりました。実行時のサブモジュール性メトリック（探索セットのJaccard係数ρ）は、**すべてのレンズペアに対して0.0**を示していますが、判断レベルのCohen κは**0.73〜0.81**です。つまり、`ρ ≤ 0.25`のゲートは、レンズ間の相関関係（κ）を*無視*しています。この点を特定することが、このスライスの主な目的です。完全な結果と方法は、[`eval/RESULTS.md`](eval/RESULTS.md)および[`design/07`](design/07-slice1-calibration.md)に記載されています。

## HTTPサービス

PrismをHTTPサービスとして実行します（`[http]`オプションが必要です）。

```bash
prism serve --host 127.0.0.1 --port 8000      # OpenAPI docs at /docs
```

| エンドポイント | 機能 |
|---|---|
| `POST /verify` | アーティファクトを検証します（CLIと同じコントラクト）。予算内で処理を完了します。`Prefer: respond-async` + `webhook` URL → `202`。検証結果は、署名されたwebhookに送信されます。 |
| `GET /replay/{receipt_id}` | 署名された検証結果 + `signature_valid`。 |
| `POST /verify-receipt` | スタンドアロンの検証結果を検証します（異なるツール間で）。 |
| `GET /healthz` | 稼働状況 + 設定された検証モデルファミリー（認証は不要）。 |

APIキーを設定します（保存時はハッシュ化されます）。Prismは、**フェイルクローズ**で動作するため、キーが設定されるか、ローカルでの認証なしの使用を選択するまで、`/verify`へのリクエストは拒否されます。

```bash
export PRISM_API_KEYS="<sha256(key1)>,<sha256(key2)>"   # callers send: Authorization: Bearer <key>
export PRISM_WEBHOOK_SECRET="<random>"                  # to sign async/escalate webhook deliveries
# local dev only:
export PRISM_HTTP_ALLOW_NO_AUTH=1
```

エラーはRFC 9457 `application/problem+json`形式で返されます。`POST /verify`は、`Idempotency-Key`ヘッダーを尊重し、キーごとのレート制限（`429` + `Retry-After`）を適用します。非同期/エスカレーションwebhookは、Standard-Webhooks形式で署名され、SSRF対策が施され（内部/メタデータターゲットは許可されません）、再試行され、名前付きのキャンセルイベント補正機能が含まれます。

## 検証結果と署名（Ed25519、誰でも検証可能）

すべての検証処理は、署名された、再現可能な検証結果を`~/.prism/receipts.db`に生成します。v0.4では、デフォルトで**Ed25519（RFC 8032）**を使用して新しい検証結果に署名するため、**別のツールを使用して、Prismの公開キーでPrismの検証結果を検証できます。共有秘密鍵は必要ありません**。

```bash
prism keygen --out ~/.prism/signing_key.pem    # generate an Ed25519 keypair
export PRISM_SIGNING_KEY=~/.prism/signing_key.pem
prism pubkey                                    # publish this public key + kid to consumers

# a consumer (e.g. role-os) verifies a receipt with ONLY the public key:
prism verify-receipt receipt.json --public-key prism-pub.pem
```

署名は、検証結果、前後のアーティファクトハッシュ、検証モデル、準単調性行列、各検証手法のプロンプトハッシュ（バイト単位で再現可能）、引用検索ピン、および署名アルゴリズム/キーIDをカバーします。従来の**HMAC**検証結果も引き続き検証できます（`PRISM_SIGNING_SECRET`を設定します）。`PRISM_DEV=1`を設定すると、ローカル環境でのテスト用に開発キーが生成されます。Prismは、キーが設定されていない場合、検証/再現/提供/MCPパスの開始を**拒否**します。これは、公開されているキーを使用して静かに署名するのではなく、より安全な方法です。

補正コマンドを使用して、保存された検証結果を管理します。

```bash
prism receipt delete <receipt_id>
prism receipt prune --older-than 90d --yes
```

## セキュリティとプライバシー

- **脅威モデル**：Prismは、渡されたアーティファクトと意図、および検証モデルの応答を読み取り、署名された検証結果をローカルのSQLiteデータベースに書き込みます。Prismは、環境変数を通じて提供されるプロバイダーAPIキーを超えて、ソースツリー、環境、または資格情報を読み取りません。検証結果の署名により、**第三者による検証が可能**になります（Ed25519：消費者は公開キーを使用して検証し、共有秘密鍵は必要ありません）。ただし、ローカルのルート権限を持つ攻撃者がオンディスクの秘密鍵を読み取ることができるため、改ざんから完全に保護されるわけではありません。これは、HMAC秘密鍵と同じレベルの保護です。真の改ざん耐性を実現するには、キーをHSMに保存し、検証結果を透過性ログに記録します（推奨されるセキュリティ強化策）。
- **HTTPインターフェース**：`prism serve`はデフォルトでループバックアドレスにバインドされ、**フェイルクローズ**で動作します（APIキーがない場合、`/verify`へのリクエストは拒否されます）。キーは保存時にハッシュ化され、呼び出し元が提供するwebhook URLに対して**SSRF対策**が施されます（内部/リンクローカル/メタデータターゲットは許可されません）。呼び出し元が提供するアーティファクトをモデルで実行します。アーティファクトは、プロンプトインジェクションを試みる可能性がありますが、検証結果のスキーマを変更したり、Prismのプロバイダーキーを外部に送信したりすることはできません。
- **テレメトリなし**：Prismは、構成されたモデルプロバイダー（Anthropic / OpenAI / Google / ローカルのOllama）にのみリクエストを送信します。それ以外には何も送信しません。
- 完全なポリシー：[SECURITY.md](SECURITY.md)。

## ライセンス

MIT
