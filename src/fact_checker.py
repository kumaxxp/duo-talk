"""
Fact Checker - Web検索を使って発言の事実確認を行うモジュール

発言から事実主張を抽出し、検索で検証して
一般常識と異なる場合は訂正指示を生成する。
"""

import re
import json
from typing import Optional
from dataclasses import dataclass

from src.llm_client import get_llm_client


@dataclass
class FactCheckResult:
    """ファクトチェックの結果"""
    has_error: bool  # 誤りがあったか
    claim: Optional[str]  # 検出した主張
    correct_info: Optional[str]  # 正しい情報
    correction_prompt: Optional[str]  # 訂正を促すプロンプト
    search_confidence: str  # "high", "medium", "low" - 検索結果の確信度
    raw_search_result: Optional[str]  # 検索結果の生データ


class FactChecker:
    """発言のファクトチェックを行うクラス"""

    def __init__(self):
        self.llm = get_llm_client()
        # 検索をスキップすべきトピック（個人的意見、感想など）
        self.skip_patterns = [
            r"美味し[いそう]",
            r"好き",
            r"嫌い",
            r"きれい",
            r"かわいい",
            r"すごい",
            r"欲しい",
            r"行きたい",
        ]

    def check_statement(
        self,
        statement: str,
        context: Optional[str] = None,
    ) -> FactCheckResult:
        """
        発言をファクトチェックする

        Args:
            statement: チェック対象の発言
            context: 会話の文脈（オプション）

        Returns:
            FactCheckResult
        """
        # Step 1: 発言から事実主張を抽出
        claims = self._extract_claims(statement)

        if not claims:
            return FactCheckResult(
                has_error=False,
                claim=None,
                correct_info=None,
                correction_prompt=None,
                search_confidence="low",
                raw_search_result=None,
            )

        # Step 2: 各主張を検索で検証
        for claim in claims:
            # スキップパターンに該当する場合は無視
            if self._should_skip(claim):
                continue

            # 検索クエリを生成
            search_query = self._generate_search_query(claim)
            if not search_query:
                continue

            # Web検索を実行
            search_result = self._web_search(search_query)
            if not search_result:
                continue

            # 検索結果を分析
            analysis = self._analyze_search_result(claim, search_result, statement)

            if analysis["has_error"] and analysis["confidence"] != "low":
                return FactCheckResult(
                    has_error=True,
                    claim=claim,
                    correct_info=analysis["correct_info"],
                    correction_prompt=self._generate_correction_prompt(
                        claim, analysis["correct_info"]
                    ),
                    search_confidence=analysis["confidence"],
                    raw_search_result=search_result,
                )

        return FactCheckResult(
            has_error=False,
            claim=None,
            correct_info=None,
            correction_prompt=None,
            search_confidence="low",
            raw_search_result=None,
        )

    def _extract_claims(self, statement: str) -> list[str]:
        """発言から検証可能な事実主張を抽出する"""
        prompt = f"""以下の発言から、検索で検証可能な「事実についての主張」を抽出してください。

【発言】
{statement}

【抽出ルール】
- 商品、食べ物、場所についての具体的な特徴や属性の主張
- 「〜は〜だ」「〜には〜がある」のような事実を述べる部分
- 感想や意見（「美味しそう」「行きたい」）は除外
- 質問形（「〜なの？」）も対象に含める（質問に含まれる前提を抽出）

【出力形式】
JSON配列で出力してください。主張がない場合は空配列 []
例: ["ストロングゼロはノンアルコール", "金閣寺は江戸時代に建てられた"]

【出力】"""

        try:
            result = self.llm.call(
                system="あなたは発言から事実主張を抽出するエキスパートです。",
                user=prompt,
                temperature=0.1,
                max_tokens=200,
            )

            # JSON配列をパース
            result = result.strip()
            if result.startswith("```"):
                match = re.search(r"```(?:json)?\s*([\s\S]*?)```", result)
                if match:
                    result = match.group(1).strip()

            claims = json.loads(result)
            return claims if isinstance(claims, list) else []

        except Exception as e:
            print(f"[FactChecker] 主張抽出エラー: {e}")
            return []

    def _should_skip(self, claim: str) -> bool:
        """この主張をスキップすべきか判定"""
        for pattern in self.skip_patterns:
            if re.search(pattern, claim):
                return True
        return False

    def _generate_search_query(self, claim: str) -> Optional[str]:
        """主張から検索クエリを生成"""
        prompt = f"""以下の主張を検証するための検索クエリを1つ生成してください。

【主張】
{claim}

【ルール】
- 主要なキーワードを含む簡潔なクエリ
- 日本語で出力
- クエリのみを出力（説明不要）

【検索クエリ】"""

        try:
            result = self.llm.call(
                system="検索クエリを生成するアシスタントです。",
                user=prompt,
                temperature=0.1,
                max_tokens=50,
            )
            return result.strip().strip('"').strip("'")
        except Exception:
            return None

    def _web_search(self, query: str) -> Optional[str]:
        """Web検索を実行（DuckDuckGo APIを使用）"""
        try:
            from duckduckgo_search import DDGS

            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=5))

            if not results:
                return None

            # 検索結果を整形
            search_text = ""
            for i, r in enumerate(results, 1):
                title = r.get("title", "")
                body = r.get("body", "")
                search_text += f"【結果{i}】{title}\n{body}\n\n"

            return search_text

        except ImportError:
            print("[FactChecker] duckduckgo-search がインストールされていません")
            print("pip install duckduckgo-search でインストールしてください")
            return None
        except Exception as e:
            print(f"[FactChecker] 検索エラー: {e}")
            return None

    def _analyze_search_result(
        self,
        claim: str,
        search_result: str,
        original_statement: str,
    ) -> dict:
        """検索結果を分析して主張の正誤を判定"""
        prompt = f"""以下の主張が検索結果と一致するか分析してください。

【検証する主張】
{claim}

【元の発言】
{original_statement}

【検索結果】
{search_result}

【分析ルール】
- 主張が検索結果と明らかに矛盾する場合 → has_error: true
- 検索結果が不十分/曖昧な場合 → confidence: "low" として誤りとしない
- 検索結果が明確に主張を否定する場合 → confidence: "high"
- 一般的に知られている情報かどうかも考慮

【出力形式】
JSON:
{{
  "has_error": true/false,
  "confidence": "high" | "medium" | "low",
  "correct_info": "正しい情報（誤りがある場合）",
  "reasoning": "判断理由"
}}

【分析結果】"""

        try:
            result = self.llm.call(
                system="あなたは事実検証の専門家です。検索結果を元に主張の正誤を判定します。",
                user=prompt,
                temperature=0.1,
                max_tokens=300,
            )

            # JSONをパース
            result = result.strip()
            if result.startswith("```"):
                match = re.search(r"```(?:json)?\s*([\s\S]*?)```", result)
                if match:
                    result = match.group(1).strip()

            analysis = json.loads(result)
            return {
                "has_error": analysis.get("has_error", False),
                "confidence": analysis.get("confidence", "low"),
                "correct_info": analysis.get("correct_info", ""),
                "reasoning": analysis.get("reasoning", ""),
            }

        except Exception as e:
            print(f"[FactChecker] 分析エラー: {e}")
            return {
                "has_error": False,
                "confidence": "low",
                "correct_info": "",
                "reasoning": str(e),
            }

    def _generate_correction_prompt(
        self,
        incorrect_claim: str,
        correct_info: str,
    ) -> str:
        """訂正を促すプロンプトを生成"""
        return f"""【ファクトチェック指摘】
姉様の発言に誤りがあります。
- 誤り: {incorrect_claim}
- 正しい情報: {correct_info}

次の発言では、この誤りを自然に訂正してください。
例: 「やな姉様、それは違いますよ。{correct_info}」
「姉様、{correct_info}なんですよ」
など、キャラクターらしく訂正してください。"""


# シングルトンインスタンス
_fact_checker: Optional[FactChecker] = None


def get_fact_checker() -> FactChecker:
    """FactCheckerのシングルトンインスタンスを取得"""
    global _fact_checker
    if _fact_checker is None:
        _fact_checker = FactChecker()
    return _fact_checker
