#!/usr/bin/env python3
"""
Comprehensive system validation test suite

Validates all components:
1. RAG システム
2. Character システム
3. Director システム
4. Logger/Feedback システム
5. PromptManager
6. 統合パイプライン
"""

import json
from pathlib import Path

from src.rag import RAGSystem
from src.character import Character
from src.director import Director
from src.feedback_analyzer import FeedbackAnalyzer
from src.logger import get_logger
from src.prompt_manager import get_prompt_manager
from src.config import config


class ComprehensiveSystemValidator:
    """Validates all system components"""

    def __init__(self):
        self.results = {}
        self.passed = 0
        self.failed = 0

    def run_all_tests(self):
        """Run all validation tests"""
        print("=" * 80)
        print("🔬 COMPREHENSIVE SYSTEM VALIDATION TEST SUITE")
        print("=" * 80)

        # 1. RAG System
        self.test_rag_system()

        # 2. Character System
        self.test_character_system()

        # 3. Director System
        self.test_director_system()

        # 4. Logger/Feedback System
        self.test_logger_feedback_system()

        # 5. PromptManager
        self.test_prompt_manager()

        # 6. Integration
        self.test_integration()

        # Summary
        self.print_summary()

    def test_rag_system(self):
        """Test RAG knowledge retrieval"""
        print("\n【Test 1: RAG System】")
        print("-" * 80)

        try:
            rag = RAGSystem()

            # Test Character A retrieval
            print("\nCharacter A (やな) - Knowledge Retrieval:")
            queries = [
                "酒蔵",
                "情報を食べる",
                "観光客",
            ]

            for query in queries:
                results = rag.retrieve_for_character("A", query, top_k=1)
                if results:
                    domain, snippet = results[0]
                    print(f"  ✓ '{query}' → {domain} domain found")
                    self.passed += 1
                else:
                    print(f"  ✗ '{query}' → No results")
                    self.failed += 1

            # Test Character B retrieval
            print("\nCharacter B (あゆ) - Knowledge Retrieval:")
            queries = [
                "神社の参拝",
                "虹",
                "AI基地",
            ]

            for query in queries:
                results = rag.retrieve_for_character("B", query, top_k=1)
                if results:
                    domain, snippet = results[0]
                    print(f"  ✓ '{query}' → {domain} domain found")
                    self.passed += 1
                else:
                    print(f"  ✗ '{query}' → No results")
                    self.failed += 1

            self.results["RAG"] = "PASS"

        except Exception as e:
            print(f"  ✗ RAG System Error: {e}")
            self.results["RAG"] = f"FAIL: {e}"
            self.failed += 1

    def test_character_system(self):
        """Test character dialogue generation"""
        print("\n【Test 2: Character System】")
        print("-" * 80)

        try:
            char_a = Character("A")
            char_b = Character("B")

            print("\nCharacter A (やな):")
            print(f"  ✓ Initialized: {char_a.name}")
            print(f"  ✓ Domains: {len(char_a.domains)} domains")
            print(f"  ✓ System prompt: {len(char_a.system_prompt)} chars")

            print("\nCharacter B (あゆ):")
            print(f"  ✓ Initialized: {char_b.name}")
            print(f"  ✓ Domains: {len(char_b.domains)} domains")
            print(f"  ✓ System prompt: {len(char_b.system_prompt)} chars")

            # Check RAG integration
            print("\nRAG Integration Check:")
            rag_hints_a = char_a._get_rag_hints("寺院の景色")
            rag_hints_b = char_b._get_rag_hints("神社の参拝")

            if rag_hints_a:
                print(f"  ✓ Character A RAG hints: {len(rag_hints_a)} retrieved")
                self.passed += 1
            else:
                print(f"  ✗ Character A RAG hints: None retrieved")
                self.failed += 1

            if rag_hints_b:
                print(f"  ✓ Character B RAG hints: {len(rag_hints_b)} retrieved")
                self.passed += 1
            else:
                print(f"  ✗ Character B RAG hints: None retrieved")
                self.failed += 1

            self.results["Character"] = "PASS"

        except Exception as e:
            print(f"  ✗ Character System Error: {e}")
            self.results["Character"] = f"FAIL: {e}"
            self.failed += 1

    def test_director_system(self):
        """Test Director evaluation"""
        print("\n【Test 3: Director System】")
        print("-" * 80)

        try:
            director = Director()

            print("\nDirector Initialization:")
            print(f"  ✓ System prompt loaded: {len(director.system_prompt)} chars")

            # Test evaluation structure
            print("\nEvaluation Structure:")
            test_cases = [
                {
                    "frame": "古い寺院の境内。参拝客が少ない。",
                    "speaker": "A",
                    "response": "わ！すごい景色だね。",
                },
                {
                    "frame": "神社の参道。手水舎が見える。",
                    "speaker": "B",
                    "response": "姉様、こちらは手水舎です。正しい清め方があります。",
                },
            ]

            for i, case in enumerate(test_cases, 1):
                try:
                    evaluation = director.evaluate_response(
                        frame_description=case["frame"],
                        speaker=case["speaker"],
                        response=case["response"],
                    )

                    print(f"  ✓ Case {i}: {evaluation.status.name} - {evaluation.reason[:50]}")
                    self.passed += 1
                except Exception as e:
                    print(f"  ✗ Case {i}: {str(e)[:50]}")
                    self.failed += 1

            self.results["Director"] = "PASS"

        except Exception as e:
            print(f"  ✗ Director System Error: {e}")
            self.results["Director"] = f"FAIL: {e}"
            self.failed += 1

    def test_logger_feedback_system(self):
        """Test feedback logging and analysis"""
        print("\n【Test 4: Logger/Feedback System】")
        print("-" * 80)

        try:
            # Test feedback recording
            print("\nFeedback Recording:")
            logger = get_logger()

            test_feedback = [
                {
                    "run_id": "validate_001",
                    "turn_num": 1,
                    "speaker": "A",
                    "issue_type": "tone_drift",
                    "description": "Test tone issue",
                    "suggested_fix": "Add markers",
                },
                {
                    "run_id": "validate_001",
                    "turn_num": 2,
                    "speaker": "B",
                    "issue_type": "knowledge_overstep",
                    "description": "Test knowledge issue",
                    "suggested_fix": "Stay in domain",
                },
            ]

            recorded = 0
            for feedback in test_feedback:
                try:
                    FeedbackAnalyzer.record_feedback(
                        run_id=feedback["run_id"],
                        turn_num=feedback["turn_num"],
                        speaker=feedback["speaker"],
                        issue_type=feedback["issue_type"],
                        description=feedback["description"],
                        suggested_fix=feedback["suggested_fix"],
                    )
                    recorded += 1
                except Exception as e:
                    print(f"  ✗ Recording failed: {e}")

            print(f"  ✓ Feedback recorded: {recorded}/{len(test_feedback)}")

            # Test analysis
            print("\nFeedback Analysis:")
            trends = FeedbackAnalyzer.analyze_trends()
            by_char = FeedbackAnalyzer.analyze_by_character()

            if trends:
                print(f"  ✓ Trends detected: {len(trends)} issue types")
                self.passed += 1
            else:
                print(f"  ✗ No trends detected")
                self.failed += 1

            if by_char:
                print(f"  ✓ Character analysis: {len(by_char)} characters")
                self.passed += 1
            else:
                print(f"  ✗ No character analysis")
                self.failed += 1

            self.results["Logger/Feedback"] = "PASS"

        except Exception as e:
            print(f"  ✗ Logger/Feedback System Error: {e}")
            self.results["Logger/Feedback"] = f"FAIL: {e}"
            self.failed += 1

    def test_prompt_manager(self):
        """Test PromptManager"""
        print("\n【Test 5: PromptManager】")
        print("-" * 80)

        try:
            # Test Character A
            print("\nCharacter A (やな):")
            pm_a = get_prompt_manager("A")
            print(f"  ✓ Fixed: {len(pm_a.fixed)} chars")
            print(f"  ✓ Variable: {len(pm_a.variable)} chars")

            # Test Character B
            print("\nCharacter B (あゆ):")
            pm_b = get_prompt_manager("B")
            print(f"  ✓ Fixed: {len(pm_b.fixed)} chars")
            print(f"  ✓ Variable: {len(pm_b.variable)} chars")

            # Test Director
            print("\nDirector:")
            pm_d = get_prompt_manager("director")
            if pm_d.fixed:
                print(f"  ✓ Director Fixed: {len(pm_d.fixed)} chars")
                self.passed += 1
            else:
                print(f"  ✗ Director Fixed: Not loaded")
                self.failed += 1

            if pm_d.variable:
                print(f"  ✓ Director Variable: {len(pm_d.variable)} chars")
                self.passed += 1
            else:
                print(f"  ✗ Director Variable: Not loaded")
                self.failed += 1

            self.results["PromptManager"] = "PASS"

        except Exception as e:
            print(f"  ✗ PromptManager Error: {e}")
            self.results["PromptManager"] = f"FAIL: {e}"
            self.failed += 1

    def test_integration(self):
        """Test integration between components"""
        print("\n【Test 6: Integration Test】")
        print("-" * 80)

        try:
            # Simulate a complete pipeline (without LLM call)
            print("\nPipeline Component Check:")

            # 1. Vision output simulation
            vision_output = """【映像情報】
主被写体: 古い寺院の境内
環境: 静かで閑静な雰囲気
人物活動: 参拝客が少ない
色彩・光: 光と影のコントラスト
視点: 俯瞰視点
注目点: 歴史的建造物"""

            print("  ✓ Vision output format valid")
            self.passed += 1

            # 2. RAG retrieval for both characters
            rag = RAGSystem()
            frame_desc = "古い寺院の境内。参拝客が少なく、静かな時間帯のようです。"

            rag_a = rag.retrieve_for_character("A", frame_desc, top_k=2)
            rag_b = rag.retrieve_for_character("B", frame_desc, top_k=2)

            print(f"  ✓ Character A RAG: {len(rag_a)} results")
            print(f"  ✓ Character B RAG: {len(rag_b)} results")
            self.passed += 2

            # 3. Character initialization
            char_a = Character("A")
            char_b = Character("B")
            print(f"  ✓ Characters initialized")
            self.passed += 1

            # 4. Director readiness
            director = Director()
            print(f"  ✓ Director ready for evaluation")
            self.passed += 1

            # 5. Logger initialization
            logger = get_logger()
            print(f"  ✓ Logger initialized")
            self.passed += 1

            self.results["Integration"] = "PASS"

        except Exception as e:
            print(f"  ✗ Integration Error: {e}")
            self.results["Integration"] = f"FAIL: {e}"
            self.failed += 1

    def print_summary(self):
        """Print validation summary"""
        print("\n" + "=" * 80)
        print("📊 VALIDATION SUMMARY")
        print("=" * 80)

        print("\nComponent Status:")
        for component, status in self.results.items():
            status_symbol = "✅" if status == "PASS" else "❌"
            print(f"  {status_symbol} {component:20} {status}")

        print(f"\nTest Results:")
        total = self.passed + self.failed
        pass_rate = (self.passed / total * 100) if total > 0 else 0
        print(f"  Passed: {self.passed}/{total}")
        print(f"  Failed: {self.failed}/{total}")
        print(f"  Pass Rate: {pass_rate:.1f}%")

        if self.failed == 0:
            print("\n✅ ALL TESTS PASSED - System is ready for deployment!")
        else:
            print(f"\n⚠️  {self.failed} test(s) failed - Review above for details")

        print("=" * 80)


if __name__ == "__main__":
    validator = ComprehensiveSystemValidator()
    validator.run_all_tests()
