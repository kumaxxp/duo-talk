"""
Director Factory: 設定に応じて適切なDirectorを返す

DIRECTOR_MODE環境変数で切り替え:
- "minimal": DirectorMinimal（静的チェックのみ）
- "full": Director（全機能）
"""

from typing import Union

from src.config import config


# 型エイリアス（両方のDirectorに共通するインターフェース）
DirectorProtocol = Union["Director", "DirectorMinimal"]

# シングルトンインスタンス
_director_instance: DirectorProtocol = None


def get_director(force_mode: str = None) -> DirectorProtocol:
    """
    設定に応じたDirectorインスタンスを取得

    Args:
        force_mode: 強制的にモードを指定（"minimal" or "full"）
                    Noneの場合は設定から読み取る

    Returns:
        DirectorMinimal または Director のインスタンス
    """
    global _director_instance

    mode = force_mode or config.director_mode

    # モード変更時はインスタンスを再作成
    if _director_instance is not None:
        current_is_minimal = type(_director_instance).__name__ == "DirectorMinimal"
        requested_minimal = mode == "minimal"
        if current_is_minimal != requested_minimal:
            _director_instance = None

    if _director_instance is None:
        if mode == "minimal":
            from src.director_minimal import DirectorMinimal
            _director_instance = DirectorMinimal()
            print("    🎬 Director: Minimal mode (静的チェックのみ)")
        else:
            from src.director import Director
            _director_instance = Director(enable_fact_check=False)  # ファクトチェックも無効化
            print("    🎬 Director: Full mode (全機能)")

    return _director_instance


def reset_director() -> None:
    """Directorインスタンスをリセット（テスト用）"""
    global _director_instance
    _director_instance = None
