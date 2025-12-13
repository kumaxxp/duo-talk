#!/usr/bin/env python3
"""
Main script to generate commentary for frames.
"""

import sys
import argparse
import uuid
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import config
from src.character import Character
from src.director import Director
from src.validator import Validator
from src.logger import get_logger
from src.types import Frame, Turn


def run_commentary(
    frame_descriptions: list,
    max_turns_per_frame: int = 2,
    output_format: str = "text",
):
    """
    Run commentary generation for a sequence of frames.

    Args:
        frame_descriptions: List of frame descriptions
        max_turns_per_frame: Max dialogue turns per frame
        output_format: "text" or "json"
    """
    run_id = str(uuid.uuid4())[:8]
    logger = get_logger()

    # Initialize characters and director
    char_a = Character("A")
    char_b = Character("B")
    director = Director()

    # Log run start
    logger.log_run_start(
        run_id=run_id,
        frame_count=len(frame_descriptions),
        metadata={"max_turns_per_frame": max_turns_per_frame},
    )

    print(f"\n🎬 Starting commentary run: {run_id}")
    print(f"📹 Processing {len(frame_descriptions)} frames\n")

    all_turns = []
    global_turn_num = 0

    # Process each frame
    for frame_num, frame_desc in enumerate(frame_descriptions, start=1):
        print(f"\n{'='*60}")
        print(f"Frame {frame_num}: {frame_desc[:50]}...")
        print(f"{'='*60}")

        frame = Frame(frame_num=frame_num, description=frame_desc)
        frame_turns = []
        conversation = []  # (speaker, text) tuples for this frame

        # Generate dialogue for this frame
        for turn_in_frame in range(max_turns_per_frame):
            global_turn_num += 1

            # Determine who speaks (alternating: A, B, A, B, ...)
            speaker = "A" if turn_in_frame % 2 == 0 else "B"
            character = char_a if speaker == "A" else char_b

            print(f"\n[Turn {global_turn_num}] Waiting for {speaker}...")

            # Get partner's last speech (if any)
            partner_speech = None
            if conversation:
                partner_speech = conversation[-1][1]

            # Get director instruction
            director_instruction = director.get_instruction_for_next_turn(
                frame_description=frame_desc,
                conversation_so_far=conversation,
                turn_number=turn_in_frame + 1,
            )

            # Character generates response
            try:
                response = character.speak(
                    frame_description=frame_desc,
                    partner_speech=partner_speech,
                    director_instruction=director_instruction or None,
                )
            except Exception as e:
                print(f"❌ Error generating response: {e}")
                logger.log_error(run_id, global_turn_num, str(e))
                continue

            print(f"✅ {speaker}: {response}")

            # Director evaluates response
            evaluation = director.evaluate_response(
                frame_description=frame_desc,
                speaker=speaker,
                response=response,
                partner_previous_speech=partner_speech,
                speaker_domains=character.domains,
            )

            print(f"   [Director] {evaluation.status}: {evaluation.reason}")

            # If director says retry, try once more
            if evaluation.status.value == "RETRY":
                print(f"   [Director] Retrying...")
                try:
                    response = character.speak(
                        frame_description=frame_desc,
                        partner_speech=partner_speech,
                        director_instruction="Try a different angle.",
                    )
                    print(f"✅ {speaker}: {response}")
                    evaluation = director.evaluate_response(
                        frame_description=frame_desc,
                        speaker=speaker,
                        response=response,
                        partner_previous_speech=partner_speech,
                        speaker_domains=character.domains,
                    )
                    print(f"   [Director] {evaluation.status}: {evaluation.reason}")
                except Exception as e:
                    print(f"❌ Retry failed: {e}")
                    logger.log_error(run_id, global_turn_num, f"Retry failed: {str(e)}")

            # Validate response
            val_result = Validator.validate(response, speaker)
            if not val_result.is_valid:
                print(f"   ⚠️  Validation issues: {', '.join(val_result.issues)}")
                for sugg in val_result.suggestions:
                    print(f"      → {sugg}")

            # Log turn
            logger.log_turn(
                run_id=run_id,
                turn_num=global_turn_num,
                frame_num=frame_num,
                speaker=speaker,
                text=response,
                director_instruction=director_instruction,
                rag_hints=[],  # Could be enhanced
            )

            logger.log_director_check(
                run_id=run_id,
                turn_num=global_turn_num,
                speaker=speaker,
                status=evaluation.status.value,
                reason=evaluation.reason,
                suggestion=evaluation.suggestion,
            )

            logger.log_validation(
                run_id=run_id,
                turn_num=global_turn_num,
                speaker=speaker,
                is_valid=val_result.is_valid,
                issues=val_result.issues,
            )

            # Add to conversation history
            turn_obj = Turn(
                turn_num=global_turn_num,
                frame_num=frame_num,
                speaker=speaker,
                text=response,
                director_instruction=director_instruction,
                evaluation=evaluation,
            )
            frame_turns.append(turn_obj)
            all_turns.append(turn_obj)
            conversation.append((speaker, response))

            # Stop if director says we should modify (implying something's wrong)
            if evaluation.status.value == "MODIFY" and evaluation.suggestion:
                print(f"   [Director] Stopping this frame: {evaluation.suggestion}")
                break

        print(f"\nFrame {frame_num} completed with {len(frame_turns)} turns")

    # Log run end
    logger.log_run_end(run_id=run_id, total_turns=global_turn_num)

    # Print summary
    print(f"\n{'='*60}")
    print(f"✅ Commentary run completed: {run_id}")
    print(f"📊 Total turns: {global_turn_num}")
    print(f"📁 Logged to: {config.log_dir / 'commentary_runs.jsonl'}")
    print(f"{'='*60}\n")

    return {
        "run_id": run_id,
        "frame_count": len(frame_descriptions),
        "total_turns": global_turn_num,
        "turns": all_turns,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate AI commentary for tourism/drone footage"
    )
    parser.add_argument(
        "frames",
        nargs="+",
        help="Frame descriptions (quote each if it contains spaces)",
    )
    parser.add_argument(
        "--max-turns-per-frame",
        type=int,
        default=2,
        help="Maximum dialogue turns per frame (default: 2)",
    )
    parser.add_argument(
        "--output-format",
        default="text",
        choices=["text", "json"],
        help="Output format",
    )

    args = parser.parse_args()

    # Validate config
    if not config.validate():
        print("⚠️  Warning: Some persona files are missing. Using defaults.")

    # Run commentary
    result = run_commentary(
        frame_descriptions=args.frames,
        max_turns_per_frame=args.max_turns_per_frame,
        output_format=args.output_format,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
