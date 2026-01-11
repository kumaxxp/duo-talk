# AITuber RAGシステム アーキテクチャ図集

## 1. 全体システム構成

```mermaid
graph TB
    subgraph "Phase 1: RAG構築 (CLI on A5000)"
        subgraph "入力データ"
            V[配信アーカイブ<br/>100時間 40GB]
            P[PDF資料<br/>1000ページ 5GB]
            I[画像素材<br/>10000枚 5GB]
        end
        
        subgraph "処理パイプライン"
            V --> W[Whisper Large-v3<br/>文字起こし]
            P --> PD[PyPDF2/PDFPlumber<br/>テキスト抽出]
            I --> IC[BLIP2/CLIP<br/>キャプション生成]
            
            W --> CS[チャンク分割器<br/>500文字/50重複]
            PD --> CS
            IC --> CS
            
            CS --> ME[メタデータ抽出<br/>感情/話者/時刻]
            ME --> EM[埋め込み生成<br/>BGE-M3 1024次元]
        end
        
        subgraph "ベクトルDB"
            EM --> QD[(Qdrant<br/>HNSW Index<br/>5-10GB)]
        end
    end
    
    subgraph "Phase 2: 利用 (duo-talk on RTX1660Ti)"
        subgraph "メモリ階層"
            R1[即時記憶<br/>Redis 20ターン]
            R2[短期記憶<br/>Redis 24h]
            R3[長期記憶<br/>Qdrant RAG]
        end
        
        subgraph "duo-talk Core"
            DM[Dialogue Manager]
            CM[Character Engine<br/>vLLM Qwen2.5]
        end
        
        U[ユーザー入力] --> DM
        DM --> R1
        DM --> R2
        DM --> R3
        QD -.検索.- R3
        R1 --> CM
        R2 --> CM
        R3 --> CM
        CM --> O[キャラクター応答]
    end
    
    style V fill:#e1f5ff
    style P fill:#e1f5ff
    style I fill:#e1f5ff
    style QD fill:#ffe1e1
    style CM fill:#e1ffe1
    style R3 fill:#fff3e1
```

---

## 2. 構築フェーズ詳細フロー

```mermaid
flowchart TD
    Start([開始: CLI実行]) --> Init[プロジェクト初期化<br/>config.yaml生成]
    
    Init --> Source{データソース<br/>タイプ判定}
    
    Source -->|動画| Video[動画処理ブランチ]
    Source -->|PDF| PDF[PDF処理ブランチ]
    Source -->|画像| Image[画像処理ブランチ]
    
    subgraph "動画処理 (最重量級)"
        Video --> V1[音声抽出<br/>FFmpeg]
        V1 --> V2[Whisper文字起こし<br/>GPU: 8-12GB<br/>50-100時間]
        V2 --> V3[タイムスタンプ付与]
        V3 --> V4[話者分離<br/>pyannote]
    end
    
    subgraph "PDF処理"
        PDF --> P1[レイアウト解析]
        P1 --> P2{画像PDF?}
        P2 -->|Yes| P3[Tesseract OCR<br/>GPU: 2-4GB]
        P2 -->|No| P4[テキスト抽出]
        P3 --> P5[構造化]
        P4 --> P5
    end
    
    subgraph "画像処理"
        Image --> I1[画像前処理<br/>リサイズ/正規化]
        I1 --> I2[BLIP2キャプション<br/>GPU: 8-10GB]
        I2 --> I3[CLIP特徴抽出]
    end
    
    V4 --> Merge[データ統合]
    P5 --> Merge
    I3 --> Merge
    
    Merge --> Chunk[チャンク分割<br/>RecursiveTextSplitter]
    
    Chunk --> Meta[メタデータ生成]
    Meta --> Embed[埋め込み生成<br/>BGE-M3<br/>GPU: 6-10GB<br/>3-5時間]
    
    Embed --> Index[Qdrantインデックス<br/>HNSW構築<br/>1-2時間]
    
    Index --> Validate[検証テスト<br/>100クエリ実行]
    
    Validate --> Report[レポート生成<br/>HTML/JSON]
    
    Report --> End([完了: DB Ready])
    
    style Video fill:#ffe1e1
    style PDF fill:#e1f5ff
    style Image fill:#e1ffe1
    style Embed fill:#fff3e1
    style Index fill:#ffe1e1
```

---

## 3. 利用フェーズ検索フロー

```mermaid
sequenceDiagram
    autonumber
    participant U as ユーザー
    participant DT as duo-talk<br/>DialogueManager
    participant R as Redis<br/>短期記憶
    participant QE as Query<br/>Encoder
    participant QD as Qdrant<br/>長期記憶
    participant LLM as vLLM<br/>Qwen2.5
    
    U->>DT: "先週話してた本は?"
    
    rect rgb(230, 245, 255)
        Note over DT: フェーズ1: 記憶検索
        DT->>R: 直近20ターン取得
        R-->>DT: recent_history[]
        
        DT->>QE: クエリベクトル化
        Note over QE: multilingual-e5-large<br/>CPU実行 ~50ms
        QE-->>DT: query_vector[1024]
        
        DT->>QD: search(vector, top_k=5,<br/>filter={character_id="yana"})
        Note over QD: HNSW検索<br/>30-100ms
        QD-->>DT: [<br/>{text, meta, score=0.85},<br/>{text, meta, score=0.82},<br/>...]
    end
    
    rect rgb(255, 243, 225)
        Note over DT: フェーズ2: コンテキスト構築
        DT->>DT: 関連性フィルタ<br/>(score >= 0.7)
        DT->>DT: プロンプト構築:<br/>system + RAG + history
    end
    
    rect rgb(225, 255, 225)
        Note over DT,LLM: フェーズ3: 生成
        DT->>LLM: generate(prompt)
        Note over LLM: vLLM推論<br/>RTX1660Ti<br/>500-1000ms
        LLM-->>DT: "あ、『三体』だよ！<br/>SF小説で面白かった"
    end
    
    DT->>R: 応答を短期記憶に保存
    DT-->>U: キャラクター応答
```

---

## 4. メモリ階層統合アーキテクチャ

```mermaid
graph TD
    subgraph "入力層"
        UI[ユーザー入力]
    end
    
    subgraph "3層メモリシステム"
        subgraph "Layer 1: 即時記憶 (Redis)"
            L1[直近20ターン<br/>容量: ~100KB<br/>レイテンシ: 1-5ms]
        end
        
        subgraph "Layer 2: 短期記憶 (Redis TTL)"
            L2[セッション要約<br/>容量: ~1MB<br/>保持: 24時間<br/>レイテンシ: 5-10ms]
        end
        
        subgraph "Layer 3: 長期記憶 (Qdrant RAG)"
            L3[全履歴・知識<br/>容量: 5-10GB<br/>保持: 永続<br/>レイテンシ: 50-200ms]
        end
    end
    
    subgraph "検索戦略"
        S1{ターン数<br/>< 20?}
        S2{セッション<br/>内?}
        S3[ベクトル検索]
    end
    
    subgraph "duo-talk処理"
        DM[Dialogue Manager]
        PR[Prompt Builder]
        LLM[vLLM Engine]
    end
    
    UI --> S1
    S1 -->|Yes| L1
    S1 -->|No| S2
    S2 -->|Yes| L2
    S2 -->|No| L3
    
    L1 --> DM
    L2 --> DM
    L3 --> S3
    S3 --> DM
    
    DM --> PR
    PR --> LLM
    LLM --> OUT[応答出力]
    
    LLM -.新エピソード.-> L1
    LLM -.要約.-> L2
    LLM -.重要イベント.-> L3
    
    style L1 fill:#e1ffe1
    style L2 fill:#fff3e1
    style L3 fill:#ffe1e1
    style LLM fill:#e1f5ff
```

---

## 5. チャンク分割戦略

```mermaid
graph LR
    subgraph "入力テキスト"
        T[長文テキスト<br/>例: 10,000文字の配信文字起こし]
    end
    
    subgraph "分割戦略"
        S1[セマンティック境界検出<br/>- 話題変更<br/>- 話者交代<br/>- 時間区切り]
        
        S2[固定サイズ分割<br/>chunk_size=500<br/>overlap=50]
    end
    
    subgraph "チャンク出力"
        C1[Chunk 1<br/>0-500文字<br/>タイムスタンプ: 00:00-02:30]
        C2[Chunk 2<br/>450-950文字<br/>タイムスタンプ: 02:15-05:00]
        C3[Chunk 3<br/>900-1400文字<br/>タイムスタンプ: 04:45-07:30]
        CN[...]
    end
    
    subgraph "メタデータ付与"
        M1[感情: excited<br/>話者: yana<br/>トピック: game]
        M2[感情: surprised<br/>話者: yana<br/>トピック: viewer_question]
        M3[感情: happy<br/>話者: yana<br/>トピック: chat]
    end
    
    T --> S1
    T --> S2
    S1 --> C1
    S2 --> C1
    S1 --> C2
    S2 --> C2
    S1 --> C3
    S2 --> C3
    
    C1 --> M1
    C2 --> M2
    C3 --> M3
    
    M1 --> E1[埋め込み1]
    M2 --> E2[埋め込み2]
    M3 --> E3[埋め込み3]
    
    style C1 fill:#e1f5ff
    style C2 fill:#ffe1e1
    style C3 fill:#e1ffe1
```

---

## 6. GPU使用率タイムライン（構築フェーズ）

```mermaid
gantt
    title A5000 GPU使用率 (100時間分データ処理)
    dateFormat HH:mm
    axisFormat %H:%M
    
    section 音声処理
    Whisper文字起こし (12GB)     :active, w1, 00:00, 50h
    
    section PDF処理
    Tesseract OCR (4GB)           :active, p1, 50:00, 5h
    
    section 画像処理
    BLIP2キャプション (10GB)      :active, i1, 55:00, 3h
    
    section 埋め込み
    BGE-M3生成 (8GB)              :active, e1, 58:00, 5h
    
    section インデックス
    Qdrant構築 (2GB)              :active, q1, 63:00, 2h
    
    section 検証
    テスト実行 (1GB)              :active, v1, 65:00, 1h
```

---

## 7. データベーススキーマ

```mermaid
erDiagram
    CHARACTERS ||--o{ CHUNKS : has
    CHUNKS ||--o{ EMBEDDINGS : generates
    CHUNKS ||--o{ METADATA : contains
    
    CHARACTERS {
        string character_id PK
        string name
        json personality
        json speaking_style
        timestamp created_at
    }
    
    CHUNKS {
        string chunk_id PK
        string character_id FK
        text content
        int chunk_index
        timestamp timestamp_start
        timestamp timestamp_end
        string source_type
        string source_path
    }
    
    EMBEDDINGS {
        string embedding_id PK
        string chunk_id FK
        float[] vector
        int vector_size
        string model_name
    }
    
    METADATA {
        string metadata_id PK
        string chunk_id FK
        string emotion
        string speaker
        string[] topics
        float energy_level
        json custom_fields
    }
```

---

## 8. CLI実行フローチャート

```mermaid
flowchart TD
    Start([ターミナル起動]) --> Check{Conda環境<br/>有効?}
    
    Check -->|No| Activate[conda activate<br/>rag-builder]
    Check -->|Yes| CD[cd ~/aituber-rag-builder]
    Activate --> CD
    
    CD --> Init[python rag_builder.py init<br/>--project-name yana]
    
    Init --> Config{config.yaml<br/>編集完了?}
    Config -->|No| Edit[設定ファイル編集<br/>- データパス<br/>- モデル選択<br/>- チャンクサイズ]
    Edit --> Config
    
    Config -->|Yes| Add[python rag_builder.py<br/>add-source --type video]
    
    Add --> Build[python rag_builder.py build<br/>--gpu-id 0 --batch-size 32]
    
    Build --> Monitor{tmux/screen<br/>使用?}
    Monitor -->|Yes| Detach[デタッチして放置<br/>50-100時間処理]
    Monitor -->|No| Wait[処理完了まで待機]
    
    Detach --> Complete{処理完了?}
    Wait --> Complete
    
    Complete -->|Error| Debug[ログ確認<br/>エラー修正]
    Debug --> Build
    
    Complete -->|Success| Index[python rag_builder.py index<br/>--qdrant-url localhost:6333]
    
    Index --> Validate[python rag_builder.py validate<br/>--test-queries queries.json]
    
    Validate --> Report[レポート確認<br/>report.html]
    
    Report --> Deploy{品質OK?}
    Deploy -->|No| Tune[パラメータ調整<br/>- chunk_size<br/>- score_threshold<br/>- top_k]
    Tune --> Build
    
    Deploy -->|Yes| End([duo-talk統合へ])
    
    style Build fill:#ffe1e1
    style Detach fill:#fff3e1
    style Deploy fill:#e1ffe1
```

---

## 9. パフォーマンス最適化ポイント

```mermaid
mindmap
    root((RAG最適化))
        構築フェーズ
            GPU活用
                バッチ処理
                Mixed Precision FP16
                Flash Attention
            データ
                重複排除
                圧縮保存
                増分更新
            並列化
                マルチプロセス
                パイプライン
                非同期IO
        利用フェーズ
            検索
                キャッシュ
                    LRU Cache
                    Redis Cache
                インデックス
                    HNSW調整
                    量子化
                フィルタ
                    メタデータ
                    時間範囲
            生成
                vLLM最適化
                    PagedAttention
                    連続バッチ
                プロンプト
                    圧縮
                    テンプレート
```

---

## 10. エラーハンドリングフロー

```mermaid
stateDiagram-v2
    [*] --> Processing
    
    Processing --> Success : 正常完了
    Processing --> GPUError : GPU OOM
    Processing --> DataError : データ破損
    Processing --> NetworkError : 接続エラー
    
    GPUError --> Retry1 : バッチサイズ半減
    Retry1 --> Processing
    Retry1 --> FallbackCPU : 3回失敗
    
    DataError --> Skip : スキップして続行
    DataError --> Abort : 致命的エラー
    
    NetworkError --> Retry2 : 5秒待機後再試行
    Retry2 --> Processing
    Retry2 --> Abort : 10回失敗
    
    Skip --> Processing
    FallbackCPU --> Processing : CPU処理(遅い)
    
    Success --> [*]
    Abort --> [*] : ログ記録・通知
    
    note right of GPUError
        対策:
        - batch_size減少
        - 画像解像度低下
        - モデル軽量化
    end note
    
    note right of DataError
        対策:
        - ファイル検証
        - エンコード確認
        - 手動修正
    end note
```

---

**ドキュメントバージョン**: v1.0  
**図集作成日**: 2025-01-11  
**対象システム**: duo-talk AITuber RAG統合
