# duo-talk v3 設計・実装ガイド

## 作成されたファイル

### 設計書
- `duo_talk_design_v3_neuro_inspired.md` - メイン設計書（Neuro-sama分析統合版）

### テンプレートファイル（templates/）

#### 1. システムプロンプト（Layer 1）
- `system_general_yana.txt` - やな（Edge AI）用
- `system_general_ayu.txt` - あゆ（Cloud AI）用

#### 2. キャラクター判断基準（Layer 2）
- `character_core_yana.yaml` - やなの判断基準
- `character_core_ayu.yaml` - あゆの判断基準

#### 3. キャラクター発話パターン（Layer 2）
- `character_patterns_yana.yaml` - やなの発話パターン
- `character_patterns_ayu.yaml` - あゆの発話パターン

## 実装の進め方

### Phase 0: プロンプト基盤改良（最優先）

#### Phase 0A: system_general.txt読込実装
**目的**: ハードコードされたシステムプロンプトをファイルベースに移行

**手順**:
1. テンプレートを実際のpersonaディレクトリにコピー
   ```bash
   cp templates/system_general_yana.txt persona/char_a/system_general.txt
   cp templates/system_general_ayu.txt persona/char_b/system_general.txt
   ```

2. `src/character.py` の `_get_system_prompt()` を修正
   - ファイルから読込
   - テンプレート変数（{name}, {sister_name}, {role}）を置換

3. 動作確認

**成功判定**:
- [ ] system_general.txtが読み込まれている
- [ ] テンプレート変数が正しく置換されている
- [ ] 既存機能が動作している

#### Phase 0B: character_core.yaml実装
**目的**: キャラクターの判断基準を機能化

**手順**:
1. テンプレートをコピー
   ```bash
   cp templates/character_core_yana.yaml persona/char_a/character_core.yaml
   cp templates/character_core_ayu.yaml persona/char_b/character_core.yaml
   ```

2. `src/character.py` に読込処理を追加
   - `_load_character_core()` メソッド実装
   - `generate_response()` に統合

**成功判定**:
- [ ] character_core.yamlが読み込まれている
- [ ] behavioral_rulesがプロンプトに含まれている
- [ ] forbidden_patternsが考慮されている

#### Phase 0C: character_patterns.yaml実装
**目的**: 発話パターンのバリエーション提供

**手順**:
1. テンプレートをコピー
   ```bash
   cp templates/character_patterns_yana.yaml persona/char_a/character_patterns.yaml
   cp templates/character_patterns_ayu.yaml persona/char_b/character_patterns.yaml
   ```

2. `src/character.py` に読込処理を追加

**成功判定**:
- [ ] character_patterns.yamlが読み込まれている
- [ ] 発話パターンがプロンプトに反映されている

### Phase 1: 状態共有基盤（すぐ効く）

詳細は `duo_talk_design_v3_neuro_inspired.md` を参照。

### Phase 2: VLM統合（視覚情報）

詳細は `duo_talk_design_v3_neuro_inspired.md` を参照。

## ファイル構成

```
duo-talk/
├── duo_talk_design_v3_neuro_inspired.md  # メイン設計書
├── templates/                            # テンプレート（このディレクトリ）
│   ├── system_general_yana.txt
│   ├── system_general_ayu.txt
│   ├── character_core_yana.yaml
│   ├── character_core_ayu.yaml
│   ├── character_patterns_yana.yaml
│   └── character_patterns_ayu.yaml
├── persona/
│   ├── char_a/  # やな用（実際に使用）
│   │   ├── system_general.txt          ← templates/からコピー
│   │   ├── character_core.yaml         ← templates/からコピー
│   │   └── character_patterns.yaml     ← templates/からコピー
│   └── char_b/  # あゆ用（実際に使用）
│       ├── system_general.txt          ← templates/からコピー
│       ├── character_core.yaml         ← templates/からコピー
│       └── character_patterns.yaml     ← templates/からコピー
└── src/
    ├── character.py  # 修正が必要
    ├── signals.py    # 新規作成（Phase 1）
    ├── injection.py  # 新規作成（Phase 1）
    └── ...
```

## 次のステップ

1. **設計書を読む**: `duo_talk_design_v3_neuro_inspired.md` を精読
2. **Phase 0A実装**: system_general.txt読込から始める
3. **動作確認**: 各Phaseごとに動作確認を行う

## Claude Code への実装依頼例

```
duo_talk_design_v3_neuro_inspired.md の Phase 0A を実装してください。

作業内容:
1. templates/ のファイルを persona/ にコピー
2. src/character.py の _get_system_prompt() を修正
3. 動作確認

成功判定基準は設計書の Phase 0A を参照。
```

## 注意事項

- **ablitatedモデルの動的切替は見送り**: 実装難易度が高いため今回は不採用
- **テンプレートは修正可**: templates/ のファイルはプロジェクトに合わせて自由に修正してください
- **段階的実装**: Phase 0 → Phase 1 → Phase 2 の順に実装を推奨

---

作成日: 2026年1月12日
対象プロジェクト: duo-talk v3
