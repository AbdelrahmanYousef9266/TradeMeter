from pydantic import BaseModel, field_validator
from datetime import datetime
from uuid import UUID


class Tick(BaseModel):
    time: datetime
    user_id: UUID
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    bar_type: str


class RawMessage(BaseModel):
    """Parsed from the TCP pipe-delimited message sent by LiveDataFeedStrategy."""
    token: str
    timestamp: datetime
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    bar_type: str

    @classmethod
    def parse(cls, raw: str) -> "RawMessage":
        """
        Parse TOKEN|TIMESTAMP|SYMBOL|OPEN|HIGH|LOW|CLOSE|VOLUME|BAR_TYPE\\n

        Raises ValueError with a descriptive message on any format error.
        """
        line = raw.strip()
        if not line:
            raise ValueError("Empty message")

        parts = line.split("|")
        if len(parts) != 9:
            raise ValueError(
                f"Expected 9 pipe-separated fields, got {len(parts)}: {line!r}"
            )

        token, timestamp_str, symbol, open_s, high_s, low_s, close_s, volume_s, bar_type = parts

        if not token:
            raise ValueError("ConnectionToken field is empty")

        try:
            timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"Invalid timestamp: {timestamp_str!r}")

        try:
            open_val  = float(open_s)
            high_val  = float(high_s)
            low_val   = float(low_s)
            close_val = float(close_s)
        except ValueError as exc:
            raise ValueError(f"Non-numeric OHLC value: {exc}") from exc

        try:
            volume_val = int(volume_s)
        except ValueError:
            raise ValueError(f"Non-integer volume: {volume_s!r}")

        return cls(
            token=token,
            timestamp=timestamp,
            symbol=symbol.strip(),
            open=open_val,
            high=high_val,
            low=low_val,
            close=close_val,
            volume=volume_val,
            bar_type=bar_type.strip(),
        )
