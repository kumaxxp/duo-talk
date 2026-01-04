#!/usr/bin/env python3
"""
8ターン対話安定性テスト（VLM画像解析付き）

ローカル画像またはシミュレート画像を使用して、
VLM解析結果を基に8ターンの対話を継続できるかテスト。
"""
import sys
import os
import time
import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw, ImageFont

from src.signals import DuoSignals, SignalEvent, EventType
from src.character import Character
from src.novelty_guard import NoveltyGuard
from src.vision_pipeline import get_vision_pipeline, VisionMode, VisionPipelineConfig


def create_simulated_image(scene_type: str = "straight") -> Image.Image:
    """
    テスト用のシミュレート画像を生成
    
    Args:
        scene_type: シーンタイプ
            - straight: 直線道路
            - curve_left: 左カーブ
            - curve_right: 右カーブ  
            - obstacle: 障害物あり
            - narrow: 狭い通路
    """
    width, height = 640, 480
    img = Image.new('RGB', (width, height), color='#404040')  # グレーの床
    draw = ImageDraw.Draw(img)
    
    # 床面（台形で奥行き表現）
    floor_color = '#606060'
    draw.polygon([
        (0, height),
        (width, height),
        (width * 0.7, height * 0.4),
        (width * 0.3, height * 0.4)
    ], fill=floor_color)
    
    # 壁（左右）
    wall_color = '#808080'
    draw.polygon([
        (0, height),
        (0, height * 0.2),
        (width * 0.3, height * 0.4),
        (width * 0.3, height * 0.4)
    ], fill=wall_color)
    draw.polygon([
        (width, height),
        (width, height * 0.2),
        (width * 0.7, height * 0.4),
        (width * 0.7, height * 0.4)
    ], fill=wall_color)
    
    # シーンに応じた要素を追加
    if scene_type == "obstacle":
        # コーン（オレンジの三角形）
        cone_x = width * 0.55
        cone_y = height * 0.6
        cone_size = 40
        draw.polygon([
            (cone_x, cone_y - cone_size),
            (cone_x - cone_size//2, cone_y),
            (cone_x + cone_size//2, cone_y)
        ], fill='#FF6600')
        
    elif scene_type == "curve_left":
        # 左カーブを示す矢印
        draw.polygon([
            (width * 0.2, height * 0.5),
            (width * 0.35, height * 0.45),
            (width * 0.35, height * 0.55)
        ], fill='#FFFF00')
        
    elif scene_type == "curve_right":
        # 右カーブを示す矢印
        draw.polygon([
            (width * 0.8, height * 0.5),
            (width * 0.65, height * 0.45),
            (width * 0.65, height * 0.55)
        ], fill='#FFFF00')
        
    elif scene_type == "narrow":
        # 狭い通路（両側に障害物）
        box_color = '#8B4513'
        draw.rectangle([
            (width * 0.1, height * 0.5),
            (width * 0.25, height * 0.7)
        ], fill=box_color)
        draw.rectangle([
            (width * 0.75, height * 0.5),
            (width * 0.9, height * 0.7)
        ], fill=box_color)
    
    # 走行ライン（中央線）
    if scene_type == "straight":
        draw.line([
            (width // 2, height),
            (width // 2, height * 0.4)
        ], fill='#FFFFFF', width=3)
    
    return img


def run_8turn_test(
    image_path: Optional[str] = None,
    turns: int = 8,
    vision_mode: str = "vlm_only",
    scene_sequence: Optional[List[str]] = None,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    8ターン対話安定性テスト
    
    Args:
        image_path: 画像パス（Noneの場合はシミュレート画像を使用）
        turns: ターン数（デフォルト8）
        vision_mode: VisionPipelineのモード
        scene_sequence: シミュレート画像のシーケンス
        verbose: 詳細出力
        
    Returns:
        テスト結果の辞書
    """
    print("=" * 70)
    print("8-Turn Dialogue Stability Test with VLM")
    print("=" * 70)
    
    # シーンシーケンス（画像がない場合）
    if scene_sequence is None:
        scene_sequence = [
            "straight",    # Turn 1-2: 直線
            "straight",    # Turn 3-4: 直線
            "obstacle",    # Turn 5-6: 障害物発見
            "curve_left",  # Turn 7-8: 左カーブ
        ]
    
    # VisionPipeline設定
    mode_map = {
        "vlm_only": VisionMode.VLM_ONLY,
        "florence_only": VisionMode.FLORENCE_ONLY,
        "vlm_with_florence": VisionMode.VLM_WITH_FLORENCE,
    }
    v_mode = mode_map.get(vision_mode, VisionMode.VLM_ONLY)
    
    config = VisionPipelineConfig(
        mode=v_mode,
        florence_enabled=(vision_mode != "vlm_only"),
        vlm_temperature=0.3,
        vlm_max_tokens=512,
    )
    pipeline = get_vision_pipeline(config)
    
    print(f"Vision mode: {vision_mode}")
    print(f"Image source: {'File' if image_path else 'Simulated'}")
    print(f"Target turns: {turns}")
    print("-" * 70)
    
    # キャラクター初期化
    DuoSignals.reset_instance()
    signals = DuoSignals()
    novelty_guard = NoveltyGuard()
    
    char_a = Character("A")  # やな
    char_b = Character("B")  # あゆ
    print("✅ Characters initialized")
    
    # 結果収集
    history: List[Dict[str, Any]] = []
    stats = {
        "total_turns": 0,
        "successful_turns": 0,
        "loop_detections": 0,
        "vlm_errors": 0,
        "dialogue_errors": 0,
        "vlm_times_ms": [],
        "dialogue_times_ms": [],
    }
    
    print("\n" + "=" * 70)
    print("Starting Dialogue Test")
    print("=" * 70)
    
    try:
        for cycle in range(turns // 2):  # 2ターン（やな+あゆ）で1サイクル
            scene_idx = min(cycle, len(scene_sequence) - 1)
            scene_type = scene_sequence[scene_idx]
            
            print(f"\n{'─' * 70}")
            print(f"[Cycle {cycle + 1}/{turns // 2}] Scene: {scene_type}")
            print(f"{'─' * 70}")
            
            # 画像準備
            if image_path:
                image = Image.open(image_path)
                print(f"   Using image: {image_path}")
            else:
                image = create_simulated_image(scene_type)
                print(f"   Using simulated image: {scene_type}")
            
            # VLM解析
            print("   Analyzing with VLM...")
            vlm_start = time.time()
            try:
                scene_facts = pipeline.process(image, mode=v_mode)
                vlm_time = (time.time() - vlm_start) * 1000
                stats["vlm_times_ms"].append(vlm_time)
                
                # scene_factsをDuoSignalsに注入
                signals.update(SignalEvent(
                    event_type=EventType.VLM,
                    data={"facts": scene_facts}
                ))
                
                # frame_description生成
                desc = scene_facts.get("description", "")
                road_info = scene_facts.get("road_info", {})
                obstacles = scene_facts.get("obstacles", [])
                warnings = scene_facts.get("warnings", [])
                
                frame_parts = []
                if road_info.get("condition"):
                    frame_parts.append(f"路面: {road_info['condition']}")
                if road_info.get("drivable_area"):
                    frame_parts.append(f"走行可能: {road_info['drivable_area']}")
                if obstacles:
                    obs_desc = ", ".join([f"{o.get('type', '障害物')}({o.get('position', '不明')})" for o in obstacles[:3]])
                    frame_parts.append(f"障害物: {obs_desc}")
                if warnings:
                    frame_parts.append(f"注意: {'; '.join(warnings[:2])}")
                
                frame_description = " / ".join(frame_parts) if frame_parts else desc[:100]
                
                if verbose:
                    print(f"   VLM result ({vlm_time:.0f}ms): {frame_description[:80]}...")
                    
            except Exception as e:
                print(f"   ❌ VLM error: {e}")
                stats["vlm_errors"] += 1
                frame_description = f"シミュレート画像: {scene_type}"
            
            # 対話生成（やな → あゆ）
            for sub_turn, (speaker, speaker_name) in enumerate([
                (char_a, "yana"),
                (char_b, "ayu")
            ]):
                turn_idx = cycle * 2 + sub_turn + 1
                print(f"\n   [Turn {turn_idx}] {speaker_name}")
                
                last_utterance = history[-1]["content"] if history else "(走行開始)"
                
                dialogue_start = time.time()
                try:
                    result = speaker.speak_v2(
                        last_utterance=last_utterance,
                        context={"history": history[-6:]},  # 直近6ターン
                        frame_description=frame_description,
                    )
                    dialogue_time = (time.time() - dialogue_start) * 1000
                    stats["dialogue_times_ms"].append(dialogue_time)
                    
                    if result["type"] == "speech":
                        content = result["content"]
                        print(f"   💬 {speaker_name}: {content}")
                        
                        history.append({
                            "speaker": speaker_name,
                            "content": content,
                            "turn": turn_idx,
                            "timestamp": datetime.now().isoformat(),
                            "scene": scene_type,
                        })
                        
                        stats["total_turns"] += 1
                        stats["successful_turns"] += 1
                        
                        # デバッグ情報
                        debug = result.get("debug", {})
                        if debug.get("loop_detected"):
                            print(f"      ⚠️ Loop detected, strategy: {debug.get('strategy')}")
                            stats["loop_detections"] += 1
                        
                        print(f"      ({dialogue_time:.0f}ms)")
                    else:
                        print(f"   ⏸️ {speaker_name}: (silence)")
                        
                except Exception as e:
                    print(f"   ❌ Dialogue error: {e}")
                    stats["dialogue_errors"] += 1
                    import traceback
                    if verbose:
                        traceback.print_exc()
            
            # 少し待機（APIレート制限対策）
            time.sleep(0.5)
            
    except KeyboardInterrupt:
        print("\n\n⚠️ Test interrupted by user")
    
    # サマリー
    print("\n" + "=" * 70)
    print("Test Summary")
    print("=" * 70)
    
    success_rate = (stats["successful_turns"] / turns * 100) if turns > 0 else 0
    avg_vlm_time = sum(stats["vlm_times_ms"]) / len(stats["vlm_times_ms"]) if stats["vlm_times_ms"] else 0
    avg_dialogue_time = sum(stats["dialogue_times_ms"]) / len(stats["dialogue_times_ms"]) if stats["dialogue_times_ms"] else 0
    
    print(f"   Total turns attempted: {turns}")
    print(f"   Successful turns: {stats['successful_turns']}")
    print(f"   Success rate: {success_rate:.1f}%")
    print(f"   Loop detections: {stats['loop_detections']}")
    print(f"   VLM errors: {stats['vlm_errors']}")
    print(f"   Dialogue errors: {stats['dialogue_errors']}")
    print(f"   Avg VLM time: {avg_vlm_time:.0f}ms")
    print(f"   Avg dialogue time: {avg_dialogue_time:.0f}ms")
    
    # 判定
    print("\n" + "-" * 70)
    if success_rate >= 100:
        print("✅ TEST PASSED: All turns completed successfully!")
    elif success_rate >= 75:
        print("⚠️ TEST PARTIAL: Most turns completed, some issues detected")
    else:
        print("❌ TEST FAILED: Significant issues detected")
    
    # 対話サンプル
    if history:
        print("\n" + "-" * 70)
        print("Dialogue Sample (all turns):")
        print("-" * 70)
        for h in history:
            speaker = h["speaker"]
            content = h["content"]
            scene = h.get("scene", "")
            print(f"[{h['turn']}] {speaker} ({scene}): {content}")
    
    print("=" * 70)
    
    return {
        "success": success_rate >= 75,
        "success_rate": success_rate,
        "stats": stats,
        "history": history,
    }


def main():
    parser = argparse.ArgumentParser(description="8-Turn Dialogue Stability Test with VLM")
    parser.add_argument("--image", "-i", default=None,
                       help="Image file path (uses simulated images if not provided)")
    parser.add_argument("--turns", "-t", type=int, default=8,
                       help="Number of dialogue turns")
    parser.add_argument("--mode", "-m", 
                       choices=["vlm_only", "florence_only", "vlm_with_florence"],
                       default="vlm_only",
                       help="Vision processing mode")
    parser.add_argument("--quiet", "-q", action="store_true",
                       help="Reduce output verbosity")
    args = parser.parse_args()
    
    result = run_8turn_test(
        image_path=args.image,
        turns=args.turns,
        vision_mode=args.mode,
        verbose=not args.quiet,
    )
    
    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
