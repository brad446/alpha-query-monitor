from typing import Optional

LEAGUE_AVG = 0.18  # Typical trainer/jockey win rate


def connections_score(trainer_win_pct: float, jockey_win_pct: float,
                      trainer_jockey_combo_pct: Optional[float] = None,
                      trainer_distance_win_pct: Optional[float] = None,
                      combo_starts: int = 0) -> float:
    """
    Pittsburgh Phil weighted heavily on the SPECIFIC jockey/trainer combination —
    not just their individual stats. A proven partnership is worth more than
    two great individuals who've never worked together.

    Combo win% is the primary driver (60% of score).
    Individual stats fill in when combo data is sparse (< 10 starts together).
    """
    if trainer_jockey_combo_pct is not None and combo_starts >= 10:
        # Established combo — trust the data
        combo_adj = (trainer_jockey_combo_pct - LEAGUE_AVG) * 40
        trainer_adj = (trainer_win_pct - LEAGUE_AVG) * 10
        jockey_adj = (jockey_win_pct - LEAGUE_AVG) * 8
        dist_adj = (trainer_distance_win_pct - LEAGUE_AVG) * 6 if trainer_distance_win_pct else 0
        return combo_adj + trainer_adj + jockey_adj + dist_adj

    elif trainer_jockey_combo_pct is not None:
        # Combo data but small sample — blend with individual stats
        combo_adj = (trainer_jockey_combo_pct - LEAGUE_AVG) * 20
        trainer_adj = (trainer_win_pct - LEAGUE_AVG) * 20
        jockey_adj = (jockey_win_pct - LEAGUE_AVG) * 12
        dist_adj = (trainer_distance_win_pct - LEAGUE_AVG) * 8 if trainer_distance_win_pct else 0
        return combo_adj + trainer_adj + jockey_adj + dist_adj

    else:
        # No combo data — fall back to individual stats
        trainer_adj = (trainer_win_pct - LEAGUE_AVG) * 25
        jockey_adj = (jockey_win_pct - LEAGUE_AVG) * 15
        dist_adj = (trainer_distance_win_pct - LEAGUE_AVG) * 10 if trainer_distance_win_pct else 0
        return trainer_adj + jockey_adj + dist_adj
