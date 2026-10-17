"""Load test for ZiraHive with Locust (free, pip install locust).

    locust -f loadtest/locustfile.py --host http://localhost:8080
    # then open http://localhost:8089, or headless:
    locust -f loadtest/locustfile.py --host http://localhost:8080 -u 20 -r 2 -t 3m --headless

Set ZIRAHIVE_USER / ZIRAHIVE_PASSWORD. Each simulated person browses photos, opens
thumbnails and watches a movie the way a browser does: 2 MB range requests, with seeks.
"""
import os
import random

from locust import HttpUser, between, task

USER = os.environ.get("ZIRAHIVE_USER", "mahbub")
PASSWORD = os.environ.get("ZIRAHIVE_PASSWORD", "supersecret")
CHUNK = 2 * 1024 * 1024


class FamilyMember(HttpUser):
    wait_time = between(1, 4)

    def on_start(self):
        r = self.client.post("/api/auth/login", json={"username": USER, "password": PASSWORD})
        r.raise_for_status()
        self.client.headers["Authorization"] = f"Bearer {r.json()['token']}"
        self.photos = [p["id"] for p in self.client.get("/api/photos?limit=200").json()["items"]]
        self.media = [m for m in self.client.get("/api/media").json() if m["size"]]

    @task(4)
    def browse_photos(self):
        self.client.get("/api/photos?limit=120", name="/api/photos")
        for pid in random.sample(self.photos, min(12, len(self.photos))):
            self.client.get(f"/api/assets/{pid}/thumb", name="/api/assets/[id]/thumb")

    @task(1)
    def open_photo(self):
        if self.photos:
            self.client.get(f"/api/assets/{random.choice(self.photos)}/preview", name="/api/assets/[id]/preview")

    @task(2)
    def watch_page(self):
        self.client.get("/api/titles?limit=24", name="/api/titles")
        self.client.get("/api/media/continue")

    @task(3)
    def stream(self):
        if not self.media:
            return
        m = random.choice(self.media)
        start = random.randrange(0, max(1, m["size"] - CHUNK))  # a seek somewhere in the film
        for i in range(3):  # then keep playing for a few chunks
            begin = start + i * CHUNK
            if begin >= m["size"]:
                break
            with self.client.get(f"/api/media/{m['id']}/stream", headers={"Range": f"bytes={begin}-{begin + CHUNK - 1}"},
                                 name="/api/media/[id]/stream", catch_response=True) as r:
                if r.status_code != 206:
                    r.failure(f"expected 206, got {r.status_code}")
