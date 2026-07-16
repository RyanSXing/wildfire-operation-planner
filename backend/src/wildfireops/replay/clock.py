from datetime import datetime, timedelta


class ReplayClock:
    def __init__(self, start_at: datetime) -> None:
        if not isinstance(start_at, datetime) or start_at.utcoffset() != timedelta(0):
            raise ValueError("start_at must be UTC")
        self._start_at = start_at
        self._current_time = start_at

    @property
    def current_time(self) -> datetime:
        return self._current_time

    def advance(self, delta: timedelta) -> datetime:
        if not isinstance(delta, timedelta) or delta < timedelta(0):
            raise ValueError("delta must be a finite nonnegative timedelta")
        try:
            advanced = self._current_time + delta
        except OverflowError:
            raise ValueError("delta moves time outside supported range") from None
        self._current_time = advanced
        return self._current_time

    def reset(self) -> datetime:
        self._current_time = self._start_at
        return self._current_time
