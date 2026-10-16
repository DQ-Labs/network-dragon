from dataclasses import dataclass

import httpx

from network_dragon.config import secret


@dataclass
class Delivery:
    outcome: str
    retry_after: int = 0


class Pushover:
    real = True

    def __init__(self, client=None):
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(10, connect=5), follow_redirects=False
        )

    def send(self, message: str) -> Delivery:
        token, user = secret("PUSHOVER_TOKEN"), secret("PUSHOVER_USER")
        if not token or not user:
            return Delivery("credentials_missing")
        try:
            response = self.client.post(
                "https://api.pushover.net/1/messages.json",
                data={
                    "token": token,
                    "user": user,
                    "title": "Network Dragon",
                    "message": message,
                    "priority": "0",
                },
            )
            if response.status_code == 429:
                retry = response.headers.get("retry-after", "3600")
                return Delivery(
                    "rate_limited", min(86400, max(60, int(retry))) if retry.isdigit() else 3600
                )
            if response.status_code >= 500:
                return Delivery("provider_unavailable")
            if response.status_code == 200 and response.json().get("status") == 1:
                return Delivery("accepted")
            return Delivery("provider_rejected")
        except (httpx.HTTPError, ValueError):
            # Never persist provider bodies or exceptions containing request secrets.
            return Delivery("ambiguous_transport_failure")


class FakePushover:
    def __init__(self, outcomes=None):
        self.messages: list[str] = []
        self.outcomes = list(outcomes or [Delivery("accepted")])

    def send(self, message):
        self.messages.append(message)
        return self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
