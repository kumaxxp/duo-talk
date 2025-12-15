"""
Vision LLM (Llama 3.2 Vision) を使用して画像を分析し、
観光地ナレーション用の視覚情報を構造化テキストで出力する。
"""

import base64
import json
import os
from pathlib import Path
from typing import Optional
import ollama


class VisionProcessor:
    """
    Llama 3.2 Vision 8B を使用して画像を分析し、
    観光地ナレーション向けの詳細な視覚情報を生成。
    """

    def __init__(self, model: str = None):
        """
        Args:
            model: 使用する Vision モデル
                  指定なしの場合は .env の VISION_MODEL または "llava:latest"
                  注意: Vision対応モデル (llava, llama3.2-vision等) が必要
        """
        self.model = model or os.getenv("VISION_MODEL", "llava:latest")

    def analyze_image(self, image_path: str) -> dict:
        """
        画像ファイルを分析し、視覚情報を構造化テキストで返す。

        Args:
            image_path: 画像ファイルのパス

        Returns:
            {
                "status": "success" | "error",
                "image_path": str,
                "visual_info": {
                    "main_subjects": str,  # メイン被写体
                    "environment": str,    # 環境・背景
                    "people_activity": str, # 人物・活動
                    "colors_lighting": str, # 色調・照明
                    "perspective": str,    # 構図・遠近感
                    "notable_details": str # 特筆すべき詳細
                },
                "raw_text": str  # LLMの生出力
            }
        """
        try:
            # 画像ファイルの存在確認
            image_file = Path(image_path)
            if not image_file.exists():
                return {
                    "status": "error",
                    "image_path": image_path,
                    "error": f"Image file not found: {image_path}"
                }

            # 画像をbase64エンコード
            with open(image_file, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")

            # Vision プロンプト
            prompt = """この画像を詳細に分析してください。以下の観点から、観光地ナレーション向けの視覚情報を日本語で提供してください：

【メイン被写体】
- 画像の中心的な被写体は何か？
- その特徴、大きさ、位置は？

【環境・背景】
- 周囲の環境はどのような状態か？
- 背景にある重要な要素は？

【人物・活動】
- 人物がいるか？いる場合の状態は？
- 何かアクティビティが起きているか？

【色調・照明】
- 全体的な色合いは？
- 光の質（朝日、逆光、曇りなど）は？

【構図・遠近感】
- 画像の構成はどうか？
- 遠近感（前景、中景、背景）の配分は？

【特筆すべき詳細】
- 観光地ナレーション時に言及すると面白い、珍しい要素は？

各項目について、簡潔かつ具体的に記述してください。"""

            # Ollama API を使用して画像分析
            response = ollama.generate(
                model=self.model,
                prompt=prompt,
                images=[image_data],
                stream=False
            )

            raw_text = response.get("response", "")

            # 応答をパース
            visual_info = self._parse_vision_response(raw_text)

            return {
                "status": "success",
                "image_path": str(image_path),
                "visual_info": visual_info,
                "raw_text": raw_text
            }

        except Exception as e:
            return {
                "status": "error",
                "image_path": image_path,
                "error": str(e)
            }

    def _parse_vision_response(self, text: str) -> dict:
        """
        Vision モデルの応答を解析し、構造化された視覚情報を生成。

        Args:
            text: LLMの応答テキスト

        Returns:
            構造化された視覚情報の辞書
        """
        # シンプルな解析（実装は応答フォーマットに応じて調整可能）
        sections = {
            "main_subjects": self._extract_section(text, "【メイン被写体】"),
            "environment": self._extract_section(text, "【環境・背景】"),
            "people_activity": self._extract_section(text, "【人物・活動】"),
            "colors_lighting": self._extract_section(text, "【色調・照明】"),
            "perspective": self._extract_section(text, "【構図・遠近感】"),
            "notable_details": self._extract_section(text, "【特筆すべき詳細】")
        }

        return sections

    @staticmethod
    def _extract_section(text: str, header: str) -> str:
        """
        テキストから特定のセクションを抽出。

        Args:
            text: 全体テキスト
            header: セクションのヘッダー

        Returns:
            抽出されたセクションのテキスト
        """
        if header not in text:
            return ""

        start = text.find(header) + len(header)
        # 次のセクションヘッダーを探す
        next_header_pos = len(text)
        for next_header in ["【", "\n\n"]:
            pos = text.find(next_header, start)
            if pos != -1 and pos < next_header_pos:
                next_header_pos = pos

        section = text[start:next_header_pos].strip()
        return section

    def format_for_character(self, visual_info: dict) -> str:
        """
        構造化された視覚情報をキャラクター用のプロンプトセクションに変換。

        Args:
            visual_info: 構造化された視覚情報

        Returns:
            キャラクター用のフォーマットされたテキスト
        """
        output = "【映像情報】\n"

        if visual_info.get("main_subjects"):
            output += f"メイン：{visual_info['main_subjects']}\n"

        if visual_info.get("environment"):
            output += f"環境：{visual_info['environment']}\n"

        if visual_info.get("people_activity"):
            output += f"人物・活動：{visual_info['people_activity']}\n"

        if visual_info.get("colors_lighting"):
            output += f"色調：{visual_info['colors_lighting']}\n"

        if visual_info.get("perspective"):
            output += f"構図：{visual_info['perspective']}\n"

        if visual_info.get("notable_details"):
            output += f"注目点：{visual_info['notable_details']}\n"

        return output
