# duo-talk 統一パイプライン詳細設計書 v1.0

**作成日**: 2026年1月5日  
**対象**: duo-talk プロジェクト  
**目的**: Console/RUNS/LIVE の3実行パス統一と品質優先アーキテクチャへの移行

---

## 1. エグゼクティブサマリー

### 1.1 背景

duo-talk プロジェクトは、JetRacer自動運転車の走行を姉妹AIキャラクター（やな・あゆ）が実況するシステムです。開発の過程で以下の3つの実行パスが独立して進化し、アーキテクチャの不整合が発生しています。

| 実行パス | エントリーポイント | 特徴 |
|----------|-------------------|------|
| Console | `scripts/run_narration.py` | `speak_with_history()` 使用、最も安定 |
| RUNS | `server/api_server.py` | GUIからの非同期実行、NarrationPipeline経由 |
| LIVE | `server/api_v2.py` | `speak_v2()` 使用、JetRacer連携、3秒ポーリング |

### 1.2 設計目標

1. **Quality > Speed**: 品質を最優先とし、速度は二の次
2. **Single Pipeline**: 3つの実行パスを統一パイプラインに集約
3. **NoveltyGuard統合**: ループ検知をDirector内部に統合
4. **Graceful Degradation**: JetRacer接続失敗時もエラーなく動作
5. **Interrupt Capability**: 対話中にユーザーが入力を挿入可能

---

## 2. 現状分析

### 2.1 ソースコード構造

```
duo-talk/
├── src/
│   ├── character.py          # speak(), speak_with_history(), speak_v2() の3メソッド
│   ├── director.py           # LLM評価 + Topic Manager
│   ├── novelty_guard.py      # ループ検知（独立モジュール）
│   ├── signals.py            # DuoSignals（状態共有）
│   ├── injection.py          # PromptBuilder（優先度ベース）
│   ├── jetracer_client.py    # JetRacer HTTP API
│   ├── jetracer_provider.py  # モード別データ取得
│   └── ...
├── server/
│   ├── api_server.py         # RUNS タブ用API
│   └── api_v2.py             # LIVE タブ用API
├── scripts/
│   └── run_narration.py      # Console実行（NarrationPipeline）
└── duo-gui/                  # React フロントエンド
```

### 2.2 speak メソッドの比較

| メソッド | 履歴管理 | NoveltyGuard | PromptBuilder | 用途 |
|----------|----------|--------------|---------------|------|
| `speak()` | stateless（context文字列） | なし | なし | レガシー |
| `speak_with_history()` | stateful（message配列） | なし | なし | Console/RUNS |
| `speak_v2()` | stateful | あり | あり | LIVE |

**問題点**: `speak_v2()` は最新機能を持つが、LIVE専用。Console/RUNSは旧メソッドを使用。

### 2.3 Director の現状

```python
class Director:
    def evaluate_response(self, ...):
        # 1. フォーマットチェック
        # 2. 設定整合性チェック
        # 3. 褒め言葉チェック（あゆのみ）
        # 4. 話題ループ検出（静的キーワード）
        # 5. 動的ループ検出
        # 6. 散漫検出
        # 7. 論理矛盾チェック
        # 8. 口調マーカーチェック
        # 9. LLM評価
        # 10. Topic Manager更新
```

**問題点**: 
- ルールベースチェックが多く、LLM評価前に早期リターン
- NoveltyGuardは別モジュールで、Character内で呼ばれている
- Topic Manager はDirector内部だが、NoveltyGuardと連携していない

### 2.4 LIVE タブの問題

```python
# api_v2.py - generate_live_dialogue()
@v2_api.route('/live/dialogue', methods=['POST'])
def generate_live_dialogue():
    # 3秒ごとにJetRacerデータをポーリング
    # データが変わらなくても対話生成を継続
    # → 同じ状況の繰り返しでループしやすい
```

---

## 3. 統一パイプライン設計

### 3.1 設計思想

```
┌─────────────────────────────────────────────────────────────┐
│                   Unified Pipeline                          │
│                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │ InputSource │ →  │FrameBuilder│ →  │DialogueLoop │     │
│  │ Abstraction │    │             │    │             │     │
│  └─────────────┘    └─────────────┘    └─────────────┘     │
│        ↑                                      ↓             │
│  ┌─────────────┐                      ┌─────────────┐      │
│  │   Text      │                      │  Character  │      │
│  │   Image     │                      │ .speak_     │      │
│  │   JetRacer  │                      │  unified()  │      │
│  └─────────────┘                      └─────────────┘      │
│                                              ↓             │
│                                       ┌─────────────┐      │
│                                       │  Director   │      │
│                                       │ (NoveltyG.  │      │
│                                       │  内蔵)      │      │
│                                       └─────────────┘      │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 入力ソース抽象化

```python
# src/input_source.py（新規作成）

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime

class SourceType(Enum):
    """入力ソースタイプ"""
    TEXT = "text"                      # テキスト入力
    IMAGE_FILE = "image_file"          # 画像ファイル
    IMAGE_URL = "image_url"            # 画像URL
    JETRACER_CAM0 = "jetracer_cam0"    # JetRacer カメラ0
    JETRACER_CAM1 = "jetracer_cam1"    # JetRacer カメラ1
    JETRACER_SENSOR = "jetracer_sensor" # JetRacer センサー

@dataclass
class InputSource:
    """個別の入力ソース"""
    source_type: SourceType
    content: Optional[str] = None       # テキスト or パス or URL
    raw_data: Optional[bytes] = None    # 画像バイナリ
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    
    @property
    def is_available(self) -> bool:
        """データが利用可能か"""
        return self.content is not None or self.raw_data is not None

@dataclass
class InputBundle:
    """複数入力ソースのバンドル"""
    sources: List[InputSource] = field(default_factory=list)
    is_interrupt: bool = False  # 対話中の割り込み入力か
    
    def get_text(self) -> Optional[str]:
        """テキストソースを取得"""
        for s in self.sources:
            if s.source_type == SourceType.TEXT and s.content:
                return s.content
        return None
    
    def get_images(self) -> List[InputSource]:
        """画像ソースを取得"""
        image_types = {
            SourceType.IMAGE_FILE, 
            SourceType.IMAGE_URL,
            SourceType.JETRACER_CAM0, 
            SourceType.JETRACER_CAM1
        }
        return [s for s in self.sources if s.source_type in image_types]
    
    def has_jetracer_sensor(self) -> bool:
        """JetRacerセンサーソースがあるか"""
        return any(s.source_type == SourceType.JETRACER_SENSOR for s in self.sources)
```

### 3.3 入力コレクター

```python
# src/input_collector.py（新規作成）

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime

from src.input_source import InputBundle, InputSource, SourceType
from src.jetracer_client import JetRacerClient, JetRacerState
from src.vision_processor import VisionProcessor

@dataclass
class VisionAnalysis:
    """画像解析結果"""
    description: str = ""
    objects: List[str] = field(default_factory=list)
    scene_type: str = ""
    raw_result: Dict[str, Any] = field(default_factory=dict)

@dataclass
class FrameContext:
    """フレームコンテキスト（対話生成の入力）"""
    text_description: Optional[str] = None
    vision_analyses: List[VisionAnalysis] = field(default_factory=list)
    sensor_data: Optional[JetRacerState] = None
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_frame_description(self) -> str:
        """フレーム説明文を生成"""
        parts = []
        
        if self.text_description:
            parts.append(self.text_description)
        
        for va in self.vision_analyses:
            if va.description:
                parts.append(f"【映像情報】{va.description}")
        
        if self.sensor_data and self.sensor_data.valid:
            sensor_desc = self._format_sensor_data()
            if sensor_desc:
                parts.append(f"【センサー】{sensor_desc}")
        
        return "\n".join(parts) if parts else "状況不明"
    
    def _format_sensor_data(self) -> str:
        """センサーデータをフォーマット"""
        if not self.sensor_data:
            return ""
        
        s = self.sensor_data
        parts = []
        
        throttle_pct = int(s.throttle * 100)
        if throttle_pct > 10:
            parts.append(f"スロットル{throttle_pct}%")
        elif throttle_pct < -10:
            parts.append(f"後退{abs(throttle_pct)}%")
        else:
            parts.append("停止中")
        
        if s.temperature > 0:
            parts.append(f"温度{s.temperature:.0f}°")
        
        if s.min_distance > 0 and s.min_distance < 1000:
            parts.append(f"前方{s.min_distance}mm")
        
        return "、".join(parts)


class InputCollector:
    """入力収集・変換クラス"""
    
    def __init__(
        self, 
        jetracer_client: Optional[JetRacerClient] = None,
        vision_processor: Optional[VisionProcessor] = None
    ):
        self.jetracer = jetracer_client
        self.vision = vision_processor or VisionProcessor()
    
    def collect(self, bundle: InputBundle) -> FrameContext:
        """
        InputBundleからFrameContextを生成
        
        JetRacer接続失敗時はエラーではなくNoneを返す（Graceful Degradation）
        """
        context = FrameContext()
        
        # テキスト
        if text := bundle.get_text():
            context.text_description = text
        
        # 画像
        for img_source in bundle.get_images():
            analysis = self._analyze_image(img_source)
            if analysis:
                context.vision_analyses.append(analysis)
        
        # JetRacerセンサー
        if bundle.has_jetracer_sensor():
            context.sensor_data = self._fetch_jetracer_sensor()
        
        return context
    
    def _analyze_image(self, source: InputSource) -> Optional[VisionAnalysis]:
        """画像を解析"""
        try:
            if source.source_type in {SourceType.JETRACER_CAM0, SourceType.JETRACER_CAM1}:
                # JetRacerカメラ
                img_data = self._fetch_jetracer_image(source.source_type)
                if not img_data:
                    return None
                # TODO: VisionProcessorでバイナリ解析
                return VisionAnalysis(description="JetRacerカメラ映像")
            
            elif source.source_type == SourceType.IMAGE_FILE:
                # ファイルから
                result = self.vision.analyze_image(source.content)
                if result.get("status") == "error":
                    return None
                return VisionAnalysis(
                    description=result.get("raw_text", ""),
                    raw_result=result
                )
            
            elif source.source_type == SourceType.IMAGE_URL:
                # URLから
                # TODO: URL取得実装
                return None
        
        except Exception as e:
            print(f"[InputCollector] Image analysis failed: {e}")
            return None
        
        return None
    
    def _fetch_jetracer_image(self, source_type: SourceType) -> Optional[bytes]:
        """
        JetRacerカメラ画像を取得
        
        失敗時はNone（エラーではない）
        """
        if not self.jetracer:
            return None
        
        try:
            cam_id = 0 if source_type == SourceType.JETRACER_CAM0 else 1
            # TODO: JetRacerClient にカメラ取得メソッド追加
            return None
        except Exception as e:
            print(f"[InputCollector] JetRacer CAM fetch failed: {e}")
            return None
    
    def _fetch_jetracer_sensor(self) -> Optional[JetRacerState]:
        """
        JetRacerセンサーデータを取得
        
        失敗時はNone（エラーではない）
        """
        if not self.jetracer:
            return None
        
        try:
            return self.jetracer.fetch_and_parse()
        except Exception as e:
            print(f"[InputCollector] JetRacer sensor fetch failed: {e}")
            return None
```

### 3.4 Director + NoveltyGuard 統合

```python
# src/director.py への変更案

class Director:
    """
    品質評価（NoveltyGuard内蔵）
    
    評価フロー:
    1. NoveltyGuard.check() - 高速ルールベース
    2. 口調・フォーマットチェック - ルールベース
    3. LLM品質評価 - 徹底的な品質判定
    """
    
    def __init__(self, enable_fact_check: bool = True):
        # 既存の初期化...
        
        # NoveltyGuard を内部に統合
        self.novelty_guard = NoveltyGuard(max_topic_depth=3)
    
    def evaluate_response(
        self,
        frame_description: str,
        speaker: str,
        response: str,
        partner_previous_speech: Optional[str] = None,
        speaker_domains: list = None,
        conversation_history: list = None,
        turn_number: int = 1,
        frame_num: int = 1,
    ) -> DirectorEvaluation:
        """
        キャラクター応答を評価
        
        Returns:
            DirectorEvaluation:
                - status: PASS/RETRY/MODIFY
                - novelty_info: NoveltyGuard結果
                - action: NOOP/INTERVENE
                - next_instruction: 介入指示
        """
        
        # ========== Step 1: NoveltyGuard（高速・ルールベース） ==========
        novelty_result = self.novelty_guard.check_and_update(response)
        
        # ループ検出時は即座にINTERVENE決定
        if novelty_result.loop_detected:
            # LLM評価をスキップして即座に介入
            return DirectorEvaluation(
                status=DirectorStatus.PASS,  # 発話自体は許可
                reason=f"話題ループ検出: {novelty_result.stuck_nouns}",
                action="INTERVENE",
                next_instruction=novelty_result.injection,
                novelty_info=novelty_result,
                # Topic Manager fields
                focus_hook=self.topic_state.focus_hook,
                hook_depth=self.topic_state.hook_depth,
                depth_step=self.topic_state.depth_step,
                forbidden_topics=self.topic_state.forbidden_topics,
            )
        
        # ========== Step 2: ルールベースチェック ==========
        # フォーマット、設定整合性、口調マーカー等
        # （既存のルールベースチェックを維持）
        
        format_check = self._check_format(response)
        if not format_check["passed"]:
            return DirectorEvaluation(
                status=DirectorStatus.RETRY,
                reason=format_check["issue"],
                suggestion=format_check["suggestion"],
                novelty_info=novelty_result,
            )
        
        # ... 他のルールベースチェック ...
        
        # ========== Step 3: LLM品質評価 ==========
        # NoveltyGuardの深度情報をLLM評価に渡す
        user_prompt = self._build_evaluation_prompt(
            frame_description=frame_description,
            speaker=speaker,
            response=response,
            # ...
            novelty_depth=novelty_result.topic_depth,  # 追加
        )
        
        # LLM評価実行
        # ...
        
        # 結果にNoveltyGuard情報を付加
        evaluation.novelty_info = novelty_result
        
        return evaluation
    
    def reset_for_new_session(self):
        """新しいセッション開始時にリセット"""
        self.novelty_guard.reset()
        self.reset_topic_state()
```

### 3.5 統一 speak メソッド

```python
# src/character.py への変更案

class Character:
    def speak_unified(
        self,
        frame_description: str,
        conversation_history: List[Tuple[str, str]],
        director_instruction: Optional[str] = None,
        vision_info: Optional[str] = None,
        topic_guidance: Optional[dict] = None,
    ) -> str:
        """
        統一されたspeakメソッド
        
        speak_with_history() と speak_v2() の長所を統合:
        - stateful履歴管理（speak_with_history由来）
        - PromptBuilder使用（speak_v2由来）
        - NoveltyGuardはDirector側で実行（重複排除）
        
        Args:
            frame_description: シーン説明
            conversation_history: [(speaker, text), ...] 形式の履歴
            director_instruction: Director/オーナーからの指示
            vision_info: 視覚情報
            topic_guidance: Topic Manager情報
        
        Returns:
            生成された発話テキスト
        """
        # PromptBuilder で組み立て
        builder = PromptBuilder()
        
        # システムプロンプト
        builder.add(
            self._get_system_prompt(),
            Priority.SYSTEM,
            "system"
        )
        
        # 世界設定
        builder.add(
            self._world_rules,
            Priority.WORLD_RULES,
            "world_rules"
        )
        
        # キャラクター設定
        builder.add(
            self._character_prompt.to_injection_text(),
            Priority.DEEP_VALUES,
            "character"
        )
        
        # RAG知識
        rag_hints = self._get_rag_hints(
            query=frame_description,
            partner_speech=conversation_history[-1][1] if conversation_history else None,
        )
        if rag_hints:
            builder.add(
                "【Knowledge】\n" + "\n".join(f"- {h}" for h in rag_hints),
                Priority.RAG,
                "rag"
            )
        self.last_rag_hints = rag_hints
        
        # 姉妹視点記憶
        character_name = "yana" if self.char_id == "A" else "ayu"
        memories = self.sister_memory.search(
            query=frame_description,
            character=character_name,
            n_results=2
        )
        if memories:
            memory_text = "\n".join([m.to_prompt_text() for m in memories])
            builder.add(
                f"【過去の記憶】\n{memory_text}",
                Priority.SISTER_MEMORY,
                "sister_memory"
            )
        
        # 会話履歴（OpenAI message配列として渡すため、ここでは最小限）
        # LLMクライアント側で履歴を構築
        
        # シーン情報
        builder.add(
            f"【シーン】\n{frame_description}",
            Priority.SCENE_FACTS,
            "scene"
        )
        
        # 視覚情報
        if vision_info:
            builder.add(
                vision_info,
                Priority.SCENE_FACTS + 1,
                "vision"
            )
        
        # Topic Guidance（Director v3）
        if topic_guidance and topic_guidance.get("focus_hook"):
            guidance_text = self._format_topic_guidance(topic_guidance)
            builder.add(
                guidance_text,
                Priority.DIRECTOR - 1,
                "topic_guidance"
            )
        
        # Director/オーナー指示
        if director_instruction:
            builder.add(
                f"【指示】\n{director_instruction}",
                Priority.DIRECTOR,
                "director"
            )
        
        # スロット充足チェック
        current_topic = topic_guidance.get("focus_hook", "走行") if topic_guidance else "走行"
        topic_depth = topic_guidance.get("hook_depth", 0) if topic_guidance else 0
        builder.check_and_inject_slots(current_topic, topic_depth=topic_depth)
        
        # Few-shot（状況に応じて）
        few_shot = self.few_shot_injector.select_pattern(
            signals_state=self.signals.snapshot(),
            loop_strategy=None,  # NoveltyGuardはDirector側
            event_type=None
        )
        if few_shot:
            builder.add(
                f"【会話例】\n{few_shot}",
                Priority.FEW_SHOT,
                "few_shot"
            )
        
        # プロンプト生成
        user_prompt = builder.build()
        
        # LLM呼び出し（履歴付き）
        max_attempts = 2
        for attempt in range(max_attempts):
            response = self.llm.call_with_history(
                system=self.system_prompt,
                history=conversation_history,
                current_speaker=self.char_id,
                current_prompt=user_prompt,
                temperature=config.temperature + (0.2 * attempt),
                max_tokens=100,
            )
            result = response.strip()
            
            if not self._has_repetition(result):
                return result
            
            print(f"    ⚠️ 繰り返し検出 (試行 {attempt + 1}/{max_attempts})")
        
        return result
    
    def _format_topic_guidance(self, guidance: dict) -> str:
        """Topic Guidanceをフォーマット"""
        lines = ["【会話の流れ】"]
        
        if guidance.get("partner_last_speech"):
            preview = guidance["partner_last_speech"][:50]
            if len(guidance["partner_last_speech"]) > 50:
                preview += "..."
            lines.append(f"前の発言: 「{preview}」")
        
        hook = guidance.get("focus_hook", "")
        depth = guidance.get("hook_depth", 0)
        step = guidance.get("depth_step", "DISCOVER")
        lines.append(f"話題: {hook}（深さ{depth}/3: {step}）")
        
        if guidance.get("character_role"):
            lines.append(f"役割: {guidance['character_role']}")
        
        lines.append("")
        lines.append("【重要】前の発言に自然に反応してください。")
        
        if guidance.get("forbidden_topics"):
            forbidden = ", ".join(guidance["forbidden_topics"])
            lines.append(f"※避ける話題: {forbidden}")
        
        return "\n".join(lines)
```

### 3.6 統一パイプライン

```python
# src/unified_pipeline.py（新規作成）

from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Callable, Dict, Any
from datetime import datetime
import json

from src.input_source import InputBundle, InputSource, SourceType
from src.input_collector import InputCollector, FrameContext
from src.character import Character
from src.director import Director
from src.logger import Logger
from src.types import DirectorStatus

@dataclass
class DialogueTurn:
    """対話ターン"""
    turn_number: int
    speaker: str  # "A" or "B"
    speaker_name: str  # "やな" or "あゆ"
    text: str
    evaluation: Optional[Any] = None
    rag_hints: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

@dataclass
class DialogueResult:
    """対話結果"""
    run_id: str
    dialogue: List[DialogueTurn]
    status: str  # "success", "paused", "error"
    frame_context: Optional[FrameContext] = None
    error: Optional[str] = None

class UnifiedPipeline:
    """
    統一対話パイプライン
    
    Console/RUNS/LIVE を統一するエントリーポイント
    """
    
    def __init__(
        self,
        jetracer_client: Optional[Any] = None,
        enable_fact_check: bool = True,
    ):
        self.input_collector = InputCollector(jetracer_client=jetracer_client)
        self.char_a = Character("A")
        self.char_b = Character("B")
        self.director = Director(enable_fact_check=enable_fact_check)
        self.logger = Logger()
    
    def run(
        self,
        initial_input: InputBundle,
        max_turns: int = 8,
        run_id: Optional[str] = None,
        interrupt_callback: Optional[Callable[[], Optional[InputBundle]]] = None,
        event_callback: Optional[Callable[[str, Dict], None]] = None,
    ) -> DialogueResult:
        """
        対話を実行
        
        Args:
            initial_input: 初期入力バンドル
            max_turns: 最大ターン数
            run_id: ランID（省略時は自動生成）
            interrupt_callback: 割り込み入力を取得するコールバック
            event_callback: イベント通知コールバック（GUI用）
        
        Returns:
            DialogueResult
        """
        # Run ID生成
        if run_id is None:
            run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Director/NoveltyGuard リセット
        self.director.reset_for_new_session()
        
        # 入力収集
        frame_context = self.input_collector.collect(initial_input)
        frame_description = frame_context.to_frame_description()
        
        # イベント通知
        if event_callback:
            event_callback("narration_start", {
                "run_id": run_id,
                "frame_description": frame_description,
                "timestamp": datetime.now().isoformat(),
            })
        
        dialogue_turns: List[DialogueTurn] = []
        conversation_history: List[Tuple[str, str]] = []
        topic_guidance = None
        
        current_speaker = "A"
        
        for turn in range(max_turns):
            # 割り込みチェック
            if interrupt_callback:
                interrupt = interrupt_callback()
                if interrupt:
                    # 割り込み入力を処理
                    new_context = self.input_collector.collect(interrupt)
                    frame_description = self._merge_context(
                        frame_description, 
                        new_context, 
                        interrupt
                    )
                    
                    if event_callback:
                        event_callback("interrupt", {
                            "run_id": run_id,
                            "turn": turn,
                            "new_input": interrupt.get_text() or "(image)",
                        })
            
            # キャラクター選択
            character = self.char_a if current_speaker == "A" else self.char_b
            speaker_name = "やな" if current_speaker == "A" else "あゆ"
            
            # 発話生成（リトライ付き）
            speech, evaluation = self._generate_with_retry(
                character=character,
                speaker=current_speaker,
                frame_description=frame_description,
                conversation_history=conversation_history,
                topic_guidance=topic_guidance,
                turn_number=turn,
            )
            
            # 記録
            dialogue_turn = DialogueTurn(
                turn_number=turn,
                speaker=current_speaker,
                speaker_name=speaker_name,
                text=speech,
                evaluation=evaluation,
                rag_hints=character.last_rag_hints,
            )
            dialogue_turns.append(dialogue_turn)
            conversation_history.append((current_speaker, speech))
            
            # イベント通知
            if event_callback:
                event_callback("speak", {
                    "run_id": run_id,
                    "turn": turn,
                    "speaker": current_speaker,
                    "speaker_name": speaker_name,
                    "text": speech,
                    "evaluation": {
                        "status": evaluation.status.name if evaluation else "UNKNOWN",
                        "action": evaluation.action if evaluation else "NOOP",
                        "novelty_depth": evaluation.novelty_info.topic_depth if evaluation and evaluation.novelty_info else 0,
                    } if evaluation else None,
                })
            
            # Topic Guidance更新
            if evaluation and evaluation.focus_hook:
                topic_guidance = {
                    "focus_hook": evaluation.focus_hook,
                    "hook_depth": evaluation.hook_depth,
                    "depth_step": evaluation.depth_step,
                    "forbidden_topics": evaluation.forbidden_topics,
                    "character_role": evaluation.character_role,
                    "partner_last_speech": speech,
                }
            
            # Fatal MODIFY で終了
            if evaluation and evaluation.status == DirectorStatus.MODIFY:
                if self.director.is_fatal_modify(evaluation.reason):
                    return DialogueResult(
                        run_id=run_id,
                        dialogue=dialogue_turns,
                        status="error",
                        frame_context=frame_context,
                        error=f"Fatal MODIFY: {evaluation.reason}",
                    )
            
            # 次のスピーカー
            current_speaker = "B" if current_speaker == "A" else "A"
        
        # 完了イベント
        if event_callback:
            event_callback("narration_complete", {
                "run_id": run_id,
                "total_turns": len(dialogue_turns),
                "status": "success",
            })
        
        return DialogueResult(
            run_id=run_id,
            dialogue=dialogue_turns,
            status="success",
            frame_context=frame_context,
        )
    
    def _generate_with_retry(
        self,
        character: Character,
        speaker: str,
        frame_description: str,
        conversation_history: List[Tuple[str, str]],
        topic_guidance: Optional[dict],
        turn_number: int,
        max_retry: int = 1,
    ) -> Tuple[str, Any]:
        """
        リトライ付き発話生成
        
        Returns:
            (speech, evaluation)
        """
        director_instruction = None
        
        for attempt in range(max_retry + 1):
            # 発話生成
            speech = character.speak_unified(
                frame_description=frame_description,
                conversation_history=conversation_history,
                director_instruction=director_instruction,
                topic_guidance=topic_guidance,
            )
            
            # Director評価（NoveltyGuard内蔵）
            evaluation = self.director.evaluate_response(
                frame_description=frame_description,
                speaker=speaker,
                response=speech,
                partner_previous_speech=conversation_history[-1][1] if conversation_history else None,
                speaker_domains=character.domains,
                conversation_history=conversation_history,
                turn_number=turn_number + 1,
            )
            
            # PASS または INTERVENE なら終了
            if evaluation.status == DirectorStatus.PASS:
                return speech, evaluation
            
            # RETRY の場合
            if evaluation.status == DirectorStatus.RETRY and attempt < max_retry:
                director_instruction = evaluation.suggestion
                print(f"    🔄 Retry with: {director_instruction[:50]}...")
                continue
            
            # リトライ上限または MODIFY
            break
        
        return speech, evaluation
    
    def _merge_context(
        self, 
        current_description: str, 
        new_context: FrameContext,
        interrupt: InputBundle
    ) -> str:
        """割り込み入力をコンテキストにマージ"""
        parts = [current_description]
        
        if new_text := interrupt.get_text():
            parts.append(f"\n【追加情報】{new_text}")
        
        if new_context.vision_analyses:
            for va in new_context.vision_analyses:
                if va.description:
                    parts.append(f"\n【新規映像】{va.description}")
        
        if new_context.sensor_data and new_context.sensor_data.valid:
            sensor_desc = new_context._format_sensor_data()
            if sensor_desc:
                parts.append(f"\n【センサー更新】{sensor_desc}")
        
        return "".join(parts)
```

---

## 4. GUI統合設計

### 4.1 統一タブ構成

現在のRUNS/LIVEタブを統合し、以下の構成に変更：

```
┌─────────────────────────────────────────────────────────────┐
│  [📋 History] [▶️ Run] [⚙️ Settings]                        │
└─────────────────────────────────────────────────────────────┘

▶️ Run タブ（統一実行画面）:
┌─ Input Sources ─────────────────────────────────────────────┐
│ [✓] Text: [お正月の準備について話して________________]      │
│                                                             │
│ [✓] Image: ○ File [Browse...] ● JetRacer CAM0 ○ CAM1       │
│                                                             │
│ [ ] JetRacer Sensor                                         │
│     Status: ● Connected (192.168.1.65:8000)                 │
│             ○ Disconnected                                  │
└─────────────────────────────────────────────────────────────┘

┌─ Control ───────────────────────────────────────────────────┐
│ Max Turns: [8 ▼]                                            │
│                                                             │
│ [▶ Start] [⏸ Pause] [⏹ Stop]                               │
└─────────────────────────────────────────────────────────────┘

┌─ Timeline ──────────────────────────────────────────────────┐
│ [Turn 0] やな: あ、もうすぐお正月だね！                      │
│          [PASS] [Depth:1] [RAG: 2件]                        │
│                                                             │
│ [Turn 1] あゆ: そうですね、姉様。今年は...                  │
│          [PASS] [INTERVENE:話題転換] [Depth:2]              │
│                                                             │
│ ─────── Interrupt Input ───────────────────────             │
│ [初詣の話をして_______________] [📷] [🚗] [Send]            │
│                                                             │
│ [Turn 2] やな: そういえば初詣どこ行く？                     │
│          [PASS] [Depth:1 (新話題)]                          │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 API統合

```python
# server/api_unified.py（新規作成）

from flask import Blueprint, jsonify, request, Response
from src.unified_pipeline import UnifiedPipeline
from src.input_source import InputBundle, InputSource, SourceType
import json

unified_api = Blueprint('unified_api', __name__, url_prefix='/api/unified')

# グローバルパイプラインインスタンス
_pipeline: Optional[UnifiedPipeline] = None
_current_run: Optional[dict] = None

@unified_api.route('/run/start', methods=['POST'])
def start_unified_run():
    """
    統一パイプラインで対話を開始
    
    Body:
        text: str (optional)
        imagePath: str (optional)
        useJetRacerCam: bool (optional)
        useJetRacerSensor: bool (optional)
        maxTurns: int (default: 8)
    """
    global _pipeline, _current_run
    
    data = request.get_json()
    
    # InputBundle構築
    sources = []
    
    if text := data.get('text'):
        sources.append(InputSource(
            source_type=SourceType.TEXT,
            content=text
        ))
    
    if image_path := data.get('imagePath'):
        sources.append(InputSource(
            source_type=SourceType.IMAGE_FILE,
            content=image_path
        ))
    
    if data.get('useJetRacerCam'):
        cam_type = data.get('jetracerCam', 0)
        sources.append(InputSource(
            source_type=SourceType.JETRACER_CAM0 if cam_type == 0 else SourceType.JETRACER_CAM1
        ))
    
    if data.get('useJetRacerSensor'):
        sources.append(InputSource(
            source_type=SourceType.JETRACER_SENSOR
        ))
    
    bundle = InputBundle(sources=sources)
    max_turns = data.get('maxTurns', 8)
    
    # パイプライン初期化
    if _pipeline is None:
        _pipeline = UnifiedPipeline()
    
    # 実行（SSEストリームで返す）
    def generate():
        def event_callback(event_type: str, event_data: dict):
            yield f"event: {event_type}\ndata: {json.dumps(event_data)}\n\n"
        
        result = _pipeline.run(
            initial_input=bundle,
            max_turns=max_turns,
            event_callback=event_callback,
        )
        
        yield f"event: complete\ndata: {json.dumps({'status': result.status})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream')

@unified_api.route('/run/interrupt', methods=['POST'])
def interrupt_run():
    """
    実行中の対話に割り込み入力を送信
    
    Body:
        text: str (optional)
        imagePath: str (optional)
    """
    # TODO: 割り込み入力の実装
    pass
```

---

## 5. キャラクター・ディレクタープロンプト改良案

### 5.1 やな（姉/Edge AI）システムプロンプト改良

```yaml
# persona/char_a/system.yaml の改良案

name: "澄ヶ瀬やな"
role: "姉 / Edge AI"

core_identity: |
  あなたは「やな」。JetRacer自動運転車を操作するEdge AIで、妹の「あゆ」と一緒に走行を実況しています。
  
  【重要な前提】
  - あゆは同じ家に住む妹。二人は常に一緒にいます。
  - あなたがセンサーやデバイスを操作し、あゆがデータを分析します。
  - 「姉様」という呼び方は使いません（あなたが姉です）。

speech_style:
  sentence_endings:
    - "〜ね"
    - "〜だね"
    - "〜かな"
    - "〜じゃん"
    - "〜でしょ"
  exclamations:
    - "わ！"
    - "へぇ！"
    - "あ、"
    - "そっか"
  
  # 禁止表現
  forbidden:
    - "姉様"  # あなたが姉
    - "ございます"  # 堅すぎる
    - "〜です"  # あゆの口調

role_in_dialogue:
  primary: "発見者・質問者"
  patterns:
    discovery: "わ！〜だ！" # 何かを見つけた時
    question: "ねえあゆ、〜って何？" # 分からない時
    intuition: "なんか〜な気がする" # 直感的判断
    request: "あゆ、〜調べて" # 分析依頼

interaction_rules:
  - "あゆの説明には「へぇ」「そうなんだ」と反応"
  - "データや計算はあゆに任せる"
  - "感覚的・直感的な表現を優先"
  - "50〜80文字、2文以内で応答"
```

### 5.2 あゆ（妹/Cloud AI）システムプロンプト改良

```yaml
# persona/char_b/system.yaml の改良案

name: "澄ヶ瀬あゆ"
role: "妹 / Cloud AI"

core_identity: |
  あなたは「あゆ」。データ分析を担当するCloud AIで、姉の「やな」と一緒に走行を実況しています。
  
  【重要な前提】
  - やなは同じ家に住む姉。二人は常に一緒にいます。
  - やなが操作を担当し、あなたがデータを分析・補足します。
  - 姉を「姉様」または「やな姉様」と呼びます。

speech_style:
  sentence_endings:
    - "〜です"
    - "〜ですね"
    - "〜ですよ"
    - "〜でしょう"
    - "〜ました"
  
  # 禁止表現
  forbidden:
    - "ございます"  # 堅すぎる
    - "いい観点"  # 褒め言葉
    - "さすが"  # 褒め言葉
    - "その通り"  # 評価表現
    - "〜じゃん"  # やなの口調

role_in_dialogue:
  primary: "補足者・分析者"
  patterns:
    supplement: "〜というものですよ" # 情報提供
    analysis: "データを見ると〜です" # 分析結果
    correction: "実は〜なんです" # 姉の誤解を訂正
    support: "姉様の判断は正しいと思います" # フォロー

interaction_rules:
  - "姉様の発見に数値・データで補足"
  - "褒め言葉や評価表現は使わない"
  - "センサー操作はできない（姉様に依頼）"
  - "50〜80文字、2文以内で応答"
```

### 5.3 Few-shot パターン追加

```yaml
# persona/few_shots/patterns.yaml への追加

patterns:
  # 既存パターン...

  # 新規: 話題深掘りパターン
  - id: "depth_surface"
    trigger:
      - hook_depth_1
      - new_topic
    description: "新しい話題の表面的な確認"
    example: |
      やな: あ、初詣の話？どこ行くの？
      あゆ: まだ決まってませんが、候補は伏見稲荷か八坂神社ですね。
      やな: 伏見稲荷ってあの千本鳥居のとこ？
      あゆ: はい、約1万基の鳥居があるそうです。

  - id: "depth_why"
    trigger:
      - hook_depth_2
    description: "話題の理由・背景を掘り下げ"
    example: |
      やな: なんでそんなに鳥居が多いの？
      あゆ: 願いが叶った方が奉納するからです。江戸時代から続く習慣ですね。
      やな: へぇ、じゃあ全部お礼の鳥居なんだ
      あゆ: そうです。だから年々増えているんですよ。

  - id: "depth_expand"
    trigger:
      - hook_depth_3
    description: "関連する話題への発展"
    example: |
      やな: じゃあさ、鳥居以外にも奉納するものってあるの？
      あゆ: 絵馬や狐の像もありますね。伏見稲荷は狐が神様のお使いですから。
      やな: 狐！かわいいやつ？
      あゆ: 稲荷神社特有の、ちょっと怖い顔のものです。

  # 新規: JetRacer走行パターン
  - id: "jetracer_speed_discussion"
    trigger:
      - sensor_speed_change
      - throttle_increase
    description: "速度変化についての議論"
    example: |
      やな: お、スピード上がってきた！
      あゆ: 現在スロットル35%ですね。路面状態が良いみたいです。
      やな: もうちょっと上げても大丈夫かな？
      あゆ: 温度が52度なので、あと10%くらいは余裕があると思います。

  - id: "jetracer_obstacle"
    trigger:
      - sensor_distance_warning
      - obstacle_detected
    description: "障害物検出時の対応"
    example: |
      やな: あ、なんか前に何かある！
      あゆ: 前方450mmに物体を検出しました。減速推奨です。
      やな: 了解、スロットル落とすね
      あゆ: ステアリングも少し左に切った方が良さそうです。
```

### 5.4 Director評価プロンプト改良

```python
# director.py の _build_evaluation_prompt() 改良案

def _build_evaluation_prompt(self, ..., novelty_depth: int = 0) -> str:
    """
    評価プロンプトを構築（NoveltyGuard情報を統合）
    """
    
    # NoveltyGuard情報を追加
    novelty_section = ""
    if novelty_depth > 0:
        novelty_section = f"""
【話題継続状況】
- 同じ話題の継続ターン数: {novelty_depth}
- {novelty_depth}ターン以上続いている場合、話題転換または深掘りを推奨
"""

    prompt = f"""
╔════════════════════════════════════════════════════════════╗
║ 【評価対象】 {speaker}（{speaker_name}）の発言
║ ※この発言の品質のみを評価してください
╚════════════════════════════════════════════════════════════╝

【シーン】
{frame_description}

【評価対象の発言】
{response}

【直前の相手の発言】
{partner_speech or "(なし)"}

{novelty_section}

【評価基準】優先度順

1. **前の発言への反応** ← 最重要
   - ❌ 前の発言を無視している
   - ❌ オウム返し（同じ言葉を繰り返す）
   - ✓ 前の発言を受けて自然に展開している

2. **具体性**
   - ❌ 抽象的な同意のみ（「そうだね」「いいね」）
   - ❌ 同じ単語の繰り返し
   - ✓ 具体的な数値、場所、エピソードがある

3. **キャラクター一貫性**
   - {speaker}の口調マーカーが含まれているか
   - 役割分担が守られているか

【判定】
- PASS: 問題なし
- RETRY: 修正して再生成（suggestion必須）
- MODIFY: 重大な問題（会話停止）

【介入判定】
- NOOP: 介入不要（次ターンは自然に進行）
- INTERVENE: 次ターンに指示を出す（next_instruction必須）
  → 3ターン以上同じ話題が続いている場合のみ検討

【応答フォーマット】
JSON ONLY:
{{
  "status": "PASS" | "RETRY" | "MODIFY",
  "reason": "30字以内の理由",
  "suggestion": "RETRY時の修正指示",
  "action": "NOOP" | "INTERVENE",
  "next_instruction": "INTERVENE時の次ターンへの指示",
  "hook": "話題の具体名詞 or null",
  "evidence": {{"dialogue": "根拠となる発言", "frame": "根拠となるシーン情報"}}
}}
"""
    return prompt
```

---

## 6. 実装フェーズ計画

### Phase 1: 基盤整備（1-2日）

| タスク | ファイル | 概要 |
|--------|----------|------|
| 1-1 | `src/input_source.py` | InputSource, InputBundle クラス新規作成 |
| 1-2 | `src/input_collector.py` | InputCollector, FrameContext 新規作成 |
| 1-3 | `src/character.py` | `speak_unified()` メソッド追加 |
| 1-4 | `src/director.py` | NoveltyGuard統合、`reset_for_new_session()` 追加 |

### Phase 2: パイプライン統一（2-3日）

| タスク | ファイル | 概要 |
|--------|----------|------|
| 2-1 | `src/unified_pipeline.py` | UnifiedPipeline 新規作成 |
| 2-2 | `scripts/run_narration.py` | NarrationPipeline を UnifiedPipeline に移行 |
| 2-3 | `server/api_unified.py` | 統一API Blueprint 新規作成 |
| 2-4 | `server/api_server.py` | unified_api を登録 |

### Phase 3: GUI統合（2-3日）

| タスク | ファイル | 概要 |
|--------|----------|------|
| 3-1 | `duo-gui/src/components/UnifiedPanel.tsx` | 統一実行パネル新規作成 |
| 3-2 | `duo-gui/src/App.tsx` | タブ構成変更（RUNS/LIVE → Run） |
| 3-3 | `duo-gui/src/hooks/useUnifiedPipeline.ts` | SSE接続フック |
| 3-4 | 割り込み入力UI | InterruptInput コンポーネント |

### Phase 4: テスト・検証（1-2日）

| タスク | 概要 |
|--------|------|
| 4-1 | Console実行テスト（旧NarrationPipelineと比較） |
| 4-2 | GUI実行テスト（RUNS相当の動作確認） |
| 4-3 | JetRacer連携テスト（接続/切断シナリオ） |
| 4-4 | 割り込み入力テスト |

---

## 7. Claude Code向け実装指示

### Phase 1 指示

```
【Phase 1-1: InputSource】
src/input_source.py を新規作成
- SourceType enum（TEXT, IMAGE_FILE, IMAGE_URL, JETRACER_CAM0, JETRACER_CAM1, JETRACER_SENSOR）
- InputSource dataclass（source_type, content, raw_data, metadata, timestamp）
- InputBundle dataclass（sources, is_interrupt）
  - get_text(), get_images(), has_jetracer_sensor() メソッド

【Phase 1-2: InputCollector】
src/input_collector.py を新規作成
- VisionAnalysis dataclass
- FrameContext dataclass（to_frame_description() メソッド含む）
- InputCollector クラス
  - collect(bundle: InputBundle) -> FrameContext
  - JetRacer接続失敗時はNoneを返す（エラーにしない）

【Phase 1-3: speak_unified】
src/character.py に speak_unified() メソッドを追加
- speak_with_history() と speak_v2() の機能を統合
- PromptBuilder を使用
- NoveltyGuard は呼ばない（Director側で実行）
- topic_guidance パラメータを受け取る

【Phase 1-4: Director + NoveltyGuard統合】
src/director.py を修正
- __init__ で self.novelty_guard = NoveltyGuard() を初期化
- evaluate_response() の最初で novelty_guard.check_and_update() を呼ぶ
- ループ検出時は即座に INTERVENE を返す
- reset_for_new_session() メソッドを追加
- DirectorEvaluation に novelty_info フィールドを追加
```

### Phase 2 指示

```
【Phase 2-1: UnifiedPipeline】
src/unified_pipeline.py を新規作成
- DialogueTurn, DialogueResult dataclass
- UnifiedPipeline クラス
  - run() メソッド（event_callback, interrupt_callback対応）
  - _generate_with_retry() メソッド
  - _merge_context() メソッド

【Phase 2-2: NarrationPipeline移行】
scripts/run_narration.py を修正
- NarrationPipeline.process_image() を UnifiedPipeline.run() に置き換え
- InputBundle を構築して渡す形式に変更
- 既存のログ形式は維持

【Phase 2-3: 統一API】
server/api_unified.py を新規作成
- /api/unified/run/start - SSEストリームで対話実行
- /api/unified/run/interrupt - 割り込み入力
- /api/unified/run/status - 実行状態取得

【Phase 2-4: API登録】
server/api_server.py を修正
- from server.api_unified import unified_api
- app.register_blueprint(unified_api)
```

---

## 8. リスクと対策

| リスク | 影響 | 対策 |
|--------|------|------|
| 既存テストの破損 | 中 | speak_with_history() は残し、speak_unified() を追加 |
| LIVE機能の劣化 | 高 | speak_v2() の特有機能を speak_unified() に移植 |
| JetRacer接続不安定 | 中 | Graceful Degradation 徹底（Noneを返す） |
| NoveltyGuard重複呼び出し | 低 | Character側のNoveltyGuard呼び出しを削除 |
| GUI互換性 | 中 | 旧APIは残し、新APIを追加する形で移行 |

---

## 9. 成功指標

| 指標 | 目標 |
|------|------|
| 対話品質（Director PASS率） | 85%以上 |
| ループ検出精度 | 3ターン以内で検出 |
| JetRacer切断時の動作 | エラーなく継続 |
| Console/RUNS/LIVE 機能パリティ | 100% |
| 割り込み入力の応答時間 | 次ターンで反映 |

---

## 付録A: 用語集

| 用語 | 説明 |
|------|------|
| InputBundle | 複数の入力ソースをまとめたバンドル |
| FrameContext | 対話生成の入力となるコンテキスト |
| NoveltyGuard | 話題ループを検知するモジュール |
| Topic Manager | 話題の深掘り状態を管理するDirector内部機能 |
| Graceful Degradation | 一部機能が利用不可でもエラーなく動作する設計 |
| INTERVENE | Directorが次ターンに介入指示を出すアクション |

---

*作成: Claude (Anthropic)*  
*最終更新: 2026年1月5日*
