from datetime import date, datetime, timedelta

# 1 -> 3 -> 7 -> 16 -> 35 -> 90, then repeats at 90
INTERVAL_SEQUENCE = [1, 3, 7, 16, 35, 90]


def next_interval(current_interval_days: int) -> int:
    """Given the current interval, return the next one in the sequence.
    Once past the last step, keep repeating the last (90-day) interval."""
    if current_interval_days in INTERVAL_SEQUENCE:
        idx = INTERVAL_SEQUENCE.index(current_interval_days)
        if idx + 1 < len(INTERVAL_SEQUENCE):
            return INTERVAL_SEQUENCE[idx + 1]
        return INTERVAL_SEQUENCE[-1]
    # unrecognized interval (shouldn't normally happen) -> fall back to first step
    return INTERVAL_SEQUENCE[0]


def compute_review_update(topic_row, reviewed_on: date = None):
    """Given a topics row and the date it's being marked reviewed,
    return (new_interval_days, new_next_review_at, new_review_count).

    - On-time or early review -> advance to the next interval
    - Late review (past next_review_at) -> repeat the current interval
    """
    if reviewed_on is None:
        reviewed_on = date.today()

    current_interval = topic_row["review_interval_days"]
    next_review_at = datetime.fromisoformat(topic_row["next_review_at"]).date()
    review_count = topic_row["review_count"]

    if reviewed_on > next_review_at:
        # late: repeat current interval, don't advance
        new_interval = current_interval
    else:
        new_interval = next_interval(current_interval)

    new_next_review_at = reviewed_on + timedelta(days=new_interval)
    return new_interval, new_next_review_at.isoformat(), review_count + 1
