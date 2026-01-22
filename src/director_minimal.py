"""
Minimal Director: キャラクター対話の最小限の品質保証

一時停止中の機能:
- LLMスコアリング（5基準評価）
- NoveltyGuard（ループ検知・切り口変更）
- ビートトラッキング（進行段階管理）
- ファクトチェック（Web検索検証）
- TopicState管理（話題深掘り段階）
- 散漫検出、論理矛盾チェック

有効な機能:
- 口調マーカーチェック（やな・あゆの口調維持）
- 褒め言葉チェック（B限定、姉妹関係性の維持）
- 設定破壊チェック（同居設定など世界観維持）
"""

import re
from typing import Optional

from src.types import DirectorEvaluation, DirectorStatus


class DirectorMinimal:
    """最小構成のディレクター: 静的チェックのみで品質保証"""

    # 設定破壊検出用: 姉妹が別居しているかのような表現（絶対禁止）
    SEPARATION_WORDS = [
        "姉様のお家", "姉様の家", "姉様の実家",
        "あゆのお家", "あゆの家", "あゆの実家",
        "やなのお家", "やなの家", "やなの実家",
        "姉の家", "妹の家", "姉の実家", "妹の実家",
        "また来てね", "また遊びに来て", "お邪魔しました",
        "実家では", "実家に", "実家の", "うちの実家",
    ]

    # あゆ（B）専用の褒め言葉チェック（やなには適用しない）
    PRAISE_WORDS_FOR_AYU = [
        "いい観点", "いい質問", "さすが", "鋭い",
        "おっしゃる通り", "その通り", "素晴らしい", "お見事",
        "よく気づ", "正解です", "大正解", "正解", "すごい", "完璧", "天才",
    ]

    def __init__(self):
        """最小構成なので、外部依存は一切なし"""
        # LLM評価プロンプト保存用（MinimalではLLMを使わないので常にNone）
        self.last_evaluation_prompt: str | None = None

    def evaluate_response(
        self,
        frame_description: str,
        speaker: str,  # "A" or "B"
        response: str,
        partner_previous_speech: Optional[str] = None,
        speaker_domains: list = None,
        conversation_history: list = None,
        turn_number: int = 1,
        frame_num: int = 1,
    ) -> DirectorEvaluation:
        """
        応答を評価する（静的チェックのみ）

        Returns:
            DirectorEvaluation: PASS/WARN/RETRY の評価結果
        """
        warnings = []

        # 1. 口調マーカーチェック
        tone_check = self._check_tone_markers(speaker, response)
        if tone_check["status"] == DirectorStatus.RETRY:
            return DirectorEvaluation(
                status=DirectorStatus.RETRY,
                reason=tone_check["issue"],
                suggestion=tone_check["suggestion"],
            )
        elif tone_check["status"] == DirectorStatus.WARN:
            warnings.append(tone_check["issue"])

        # 2. 褒め言葉チェック（Bのみ）
        praise_check = self._check_praise_words(response, speaker)
        if praise_check["status"] == DirectorStatus.RETRY:
            return DirectorEvaluation(
                status=DirectorStatus.RETRY,
                reason=praise_check["issue"],
                suggestion=praise_check["suggestion"],
            )
        elif praise_check["status"] == DirectorStatus.WARN:
            warnings.append(praise_check["issue"])

        # 3. 設定破壊チェック
        setting_check = self._check_setting_consistency(response)
        if not setting_check["passed"]:
            return DirectorEvaluation(
                status=DirectorStatus.RETRY,
                reason=setting_check["issue"],
                suggestion=setting_check["suggestion"],
            )

        # 4. 出力形式チェック（長すぎる発言）
        format_check = self._check_format(response)
        if format_check["status"] == DirectorStatus.RETRY:
            return DirectorEvaluation(
                status=DirectorStatus.RETRY,
                reason=format_check["issue"],
                suggestion=format_check["suggestion"],
            )
        elif format_check["status"] == DirectorStatus.WARN:
            warnings.append(format_check["issue"])

        # 最終判定
        if warnings:
            return DirectorEvaluation(
                status=DirectorStatus.WARN,
                reason=f"警告: {', '.join(warnings)}",
                suggestion="次のターンで改善してください",
                action="NOOP",  # 最小構成では介入しない
            )

        return DirectorEvaluation(
            status=DirectorStatus.PASS,
            reason="OK",
            action="NOOP",
        )

    def commit_evaluation(self, response: str, evaluation: DirectorEvaluation) -> None:
        """
        評価を確定する（最小構成では何もしない）

        既存のDirectorとのインターフェース互換性のため維持
        """
        pass

    def reset_for_new_session(self) -> None:
        """
        新しいセッション開始時のリセット（最小構成では何もしない）

        既存のDirectorとのインターフェース互換性のため維持
        """
        pass

    def reset_topic_state(self) -> None:
        """
        話題状態のリセット（最小構成では何もしない）

        既存のDirectorとのインターフェース互換性のため維持
        """
        pass

    @staticmethod
    def _normalize_for_checks(text: str) -> str:
        """チェック用にテキストを正規化"""
        normalized = text or ""
        # 引用・括弧内を除外
        normalized = re.sub(r"[「『][^」』]*[」』]", "", normalized)
        normalized = re.sub(r"（[^）]*）", "", normalized)
        # 句読点の正規化
        normalized = normalized.replace("｡", "。")
        normalized = re.sub(r"([！？!?.])\1+", r"\1", normalized)
        # 空白の正規化
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """テキストを文に分割"""
        if not text:
            return []
        parts = re.split(r"[。！？\n]+", text)
        return [p.strip() for p in parts if p.strip()]

    def _check_tone_markers(self, speaker: str, response: str) -> dict:
        """
        口調マーカーの多信号判定

        Score 0 -> RETRY
        Score 1 -> WARN
        Score 2+ -> PASS
        """
        normalized = self._normalize_for_checks(response)

        if speaker == "A":
            # やな（姉）の口調マーカー（感情表現・語尾）
            markers = ["わ！", "へ？", "よね", "かな", "かも", "だね", "じゃん"]
            expected_desc = ["わ！", "へ？", "〜よね", "〜かな", "〜かも", "〜だね"]
            vocab_markers = ["やだ", "ほんと", "えー", "うーん", "すっごい", "そっか", "だね", "ね。"]
        else:
            # あゆ（妹）の口調マーカー（丁寧・論理的）
            markers = ["でしょう", "ですね", "ました", "ません", "ですよ"]
            expected_desc = ["〜でしょう", "〜ですね", "〜ました", "〜ですよ"]
            vocab_markers = ["つまり", "要するに", "一般的に", "目安", "推奨", "ですね", "です。"]

        found = [marker for marker in markers if marker in normalized]
        marker_hit = len(found) >= 1
        vocab_hit = any(word in normalized for word in vocab_markers)

        # やなは「姉様」を使ってはいけない（あゆの呼び方）
        if speaker == "A" and "姉様" in normalized:
            return {
                "status": DirectorStatus.RETRY,
                "score": 0,
                "issue": "禁止ワード「姉様」を使用（やなは姉なので「姉様」は使えません）",
                "suggestion": "「姉様」はあゆを呼ぶ時の言葉です。自分のことは「私」と言ってください。",
            }

        sentences = self._split_sentences(normalized)
        sentence_count = len(sentences)

        if speaker == "A":
            style_hit = sentence_count <= 2 and ("！" in normalized or "？" in normalized)
        else:
            polite_matches = re.findall(r"(です|ます|でした|ました)", normalized)
            style_hit = len(polite_matches) >= 2

        tone_score = int(marker_hit) + int(vocab_hit) + int(style_hit)

        if tone_score >= 2:
            status = DirectorStatus.PASS
        elif tone_score == 1:
            status = DirectorStatus.WARN
        else:
            status = DirectorStatus.RETRY

        return {
            "status": status,
            "score": tone_score,
            "issue": "口調スコアが不足しています" if tone_score < 2 else "",
            "suggestion": f"以下の口調マーカーを適切に含めてください: {', '.join(expected_desc)}" if tone_score < 2 else "",
        }

    def _check_praise_words(self, response: str, speaker: str) -> dict:
        """
        褒め言葉チェック（あゆの発言のみ適用）

        評価語 + 相手への肯定 = RETRY
        評価語のみ = WARN
        """
        # やな（A）の発言には適用しない
        if speaker == "A":
            return {"status": DirectorStatus.PASS, "issue": "", "suggestion": ""}

        normalized = self._normalize_for_checks(response)
        sentences = self._split_sentences(normalized)
        recipient_tokens = ["あなた", "きみ", "ユーザー", "その答え", "その考え", "その意見", "発言", "回答"]

        for sentence in sentences:
            for word in self.PRAISE_WORDS_FOR_AYU:
                if word in sentence:
                    if any(token in sentence for token in recipient_tokens):
                        return {
                            "status": DirectorStatus.RETRY,
                            "issue": f"あゆの褒め言葉使用: 「{word}」",
                            "suggestion": "評価・判定型の表現を避け、情報提供に徹してください",
                        }
                    return {
                        "status": DirectorStatus.WARN,
                        "issue": f"評価語の使用: 「{word}」",
                        "suggestion": "評価語は避け、説明に置き換えてください",
                    }

        return {"status": DirectorStatus.PASS, "issue": "", "suggestion": ""}

    def _check_setting_consistency(self, response: str) -> dict:
        """
        設定の整合性をチェック（姉妹が別居しているかのような表現を検出）
        """
        for word in self.SEPARATION_WORDS:
            if word in response:
                return {
                    "passed": False,
                    "issue": f"設定破壊: 「{word}」は姉妹が別居しているかのような表現です",
                    "suggestion": "やなとあゆは同じ家に住んでいます。「うちに」「私たちの家」等を使ってください。",
                }

        return {"passed": True, "issue": "", "suggestion": ""}

    def _check_format(self, response: str) -> dict:
        """
        出力形式をチェック（長すぎる発言の検出）
        """
        lines = [line.strip() for line in response.split("\n") if line.strip()]

        if len(lines) >= 8:
            return {
                "status": DirectorStatus.RETRY,
                "issue": f"発言が複数行に分かれすぎています（{len(lines)}行）",
                "suggestion": "1つの連続した発言として、簡潔に出力してください。",
            }

        if len(lines) >= 6:
            return {
                "status": DirectorStatus.WARN,
                "issue": f"発言が複数行です（{len(lines)}行）",
                "suggestion": "1つの連続した発言として、簡潔に出力してください。",
            }

        return {"status": DirectorStatus.PASS, "issue": "", "suggestion": ""}


# ファクトリー関数（既存コードとの互換性のため）
_director_minimal_instance: Optional[DirectorMinimal] = None


def get_director_minimal() -> DirectorMinimal:
    """DirectorMinimalのシングルトンインスタンスを取得"""
    global _director_minimal_instance
    if _director_minimal_instance is None:
        _director_minimal_instance = DirectorMinimal()
    return _director_minimal_instance
