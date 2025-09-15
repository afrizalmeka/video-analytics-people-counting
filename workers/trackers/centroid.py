# workers/centroid.py
from collections import deque
import math

class CentroidTracker:
    def __init__(self, max_distance=60, max_miss=20):
        self.next_id = 1
        self.tracks = {}          # id -> dict(x1,y1,x2,y2,cx,cy,miss)
        self.path = {}            # id -> deque history (optional)
        self.max_distance = max_distance
        self.max_miss = max_miss

    @staticmethod
    def _centroid(d):
        return ((d["x1"] + d["x2"]) // 2, (d["y1"] + d["y2"]) // 2)

    @staticmethod
    def _dist(a, b):
        return math.hypot(a[0]-b[0], a[1]-b[1])

    def update(self, detections):
        # Step 1: mark all existing as missed
        for tid in list(self.tracks.keys()):
            self.tracks[tid]["miss"] += 1

        # Step 2: greedy assign: for each det, find closest track within threshold
        assigned_tracks = set()
        results = []

        for det in detections:
            dc = (det["cx"], det["cy"])
            best_id, best_dist = None, float("inf")

            for tid, t in self.tracks.items():
                if tid in assigned_tracks:
                    continue
                tc = (t["cx"], t["cy"])
                d = self._dist(dc, tc)
                if d < best_dist:
                    best_dist = d
                    best_id = tid

            if best_id is not None and best_dist <= self.max_distance:
                # update existing track
                self.tracks[best_id].update({
                    "x1": det["x1"], "y1": det["y1"], "x2": det["x2"], "y2": det["y2"],
                    "cx": det["cx"], "cy": det["cy"], "miss": 0
                })
                assigned_tracks.add(best_id)
                results.append({**self.tracks[best_id], "id": best_id})
                # simpan jejak centroid (opsional)
                self.path.setdefault(best_id, deque(maxlen=32)).append((det["cx"], det["cy"]))
            else:
                # create new track
                tid = self.next_id; self.next_id += 1
                self.tracks[tid] = {
                    "x1": det["x1"], "y1": det["y1"], "x2": det["x2"], "y2": det["y2"],
                    "cx": det["cx"], "cy": det["cy"], "miss": 0
                }
                assigned_tracks.add(tid)
                results.append({**self.tracks[tid], "id": tid})
                self.path[tid] = deque(maxlen=32)
                self.path[tid].append((det["cx"], det["cy"]))

        # Step 3: remove long-missed
        for tid in list(self.tracks.keys()):
            if self.tracks[tid]["miss"] > self.max_miss:
                self.tracks.pop(tid, None)
                self.path.pop(tid, None)

        # Kembalikan list track aktif (id + bbox + centroid)
        return results