from typing import Any, Text, Dict, List
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet
import requests
import json
import time
import threading
import os
import math

# ========== CONFIGURAZIONE ONOS ==========
ONOS_CONTROLLER_URL = "http://localhost:8181/onos/v1"
ONOS_USERNAME = "onos"
ONOS_PASSWORD = "rocks"

# ========== MAPPING QUALITY to MBPS value ==========
QUALITY_TO_MBPS = {
    "low": 5,
    "medium": 8,
    "high": 40
}

def quality_to_mbps(quality: str) -> float:
    q = quality.lower().strip()
    return QUALITY_TO_MBPS.get(q, 5)

# ========== DIZIONARIO eta per (MOVIE, QUALITY) ==========
ETA_MIN_DICTIONARY = {
    ("Inception", "Low"): 3.27e11,
    ("Inception", "Medium"): 3.27e11,
    ("Inception", "High"): 3.27e11,
    ("Interstellar", "Low"): 3.27e11,
    ("Interstellar", "Medium"): 3.27e11,
    ("Interstellar", "High"): 3.27e11,
    ("The Matrix", "Low"): 3.27e11,
    ("The Matrix", "Medium"): 3.27e11,
    ("The Matrix", "High"): 3.27e11,
}

# ========== LOOKUP η_min ==========
def get_eta_min_from_dict(movie: str, quality: str) -> float:
    key = (movie, quality)
    if key in ETA_MIN_DICTIONARY:
        eta = ETA_MIN_DICTIONARY[key]
        print(f"[DICT-LOOKUP] ({movie}, {quality}) → η_min = {eta:.4f}")
        return eta
    else:
        print(f"[WARNING] ({movie}, {quality}) not in dict, default η_min=1.0")
        return 1.0

# ========== UPDATE η_min: EMA ==========
def update_eta_min_ema(movie: str, quality: str, n_violations: int, n_paths: int, alpha: float = 0.3) -> float:
    """
    Metodo EMA:
      violation_ratio = n_violations / n_paths
      η_min_new = η_min_old * (1 - α * violation_ratio)
    """
    key = (movie, quality)
    eta_min_old = ETA_MIN_DICTIONARY.get(key, 1.0)

    if n_paths > 0:
        violation_ratio = n_violations / n_paths
    else:
        violation_ratio = 0.0

    eta_min_new = eta_min_old * (1.0 - alpha * violation_ratio)
    eta_min_new = max(0.5, min(2.0, eta_min_new))

    adjustment_pct = 100.0 * (eta_min_new - eta_min_old) / eta_min_old if eta_min_old != 0 else 0
    print(f"  η_min: {eta_min_old:.4f} → {eta_min_new:.4f} ({adjustment_pct:+.1f}%)")

    return eta_min_new

# ========== UPDATE η_min: PROBABILISTICO ==========
def update_eta_min_probabilistic(movie: str, quality: str, n_violations: int, n_paths: int,
                                 alpha_blend: float = 0.5) -> float:
    """
    Metodo Probabilistico:
      P_empirical = n_violations / n_paths
      λ = n_violations / n_paths
      P_model = 1 - e^(-λ)
      P_x = α_blend * P_model + (1-α_blend) * P_empirical
      η_min_new = (1 - P_x) * η_min_old
    """
    key = (movie, quality)
    eta_min_old = ETA_MIN_DICTIONARY.get(key, 1.0)

    if n_paths > 0:
        P_empirical = n_violations / n_paths
        lambda_est = n_violations / n_paths
    else:
        P_empirical = 0.0
        lambda_est = 0.0

    P_model = 1.0 - math.exp(-lambda_est)
    P_x = alpha_blend * P_model + (1.0 - alpha_blend) * P_empirical
    P_x = max(0.0, min(1.0, P_x))

    eta_min_new = (1.0 - P_x) * eta_min_old

    adjustment_pct = 100.0 * (eta_min_new - eta_min_old) / eta_min_old if eta_min_old != 0 else 0
    print(f"  η_min: {eta_min_old:.4f} → {eta_min_new:.4f} ({adjustment_pct:+.1f}%)")

    return eta_min_new

# ========== UPDATE η_min IN DICT ==========
def update_eta_min_in_dict(movie: str, quality: str, new_eta_min: float):
    global ETA_MIN_DICTIONARY
    key = (movie, quality)
    ETA_MIN_DICTIONARY[key] = round(new_eta_min, 4)
    print(f"[DICT-UPDATE] ETA_MIN_DICTIONARY[{key}] = {new_eta_min:.4f}")

# ========== ONOS CLIENT ==========
class ONOSClient:
    def __init__(self, base_url: str = ONOS_CONTROLLER_URL,
                 user: str = ONOS_USERNAME,
                 password: str = ONOS_PASSWORD):
        self.base_url = base_url
        self.auth = (user, password)
        self.timeout = 5.0

    def post_intent(self, json_data: Dict) -> bool:
        """
        POST iniziale verso l'optimization API
        """
        url = "http://localhost:8181/onos/v1/optimization/api/post"
        try:
            resp = requests.post(
                url,
                data=json.dumps(json_data),
                headers={"Content-Type": "application/json"},
                auth=self.auth,
                timeout=self.timeout
            )
            resp.raise_for_status()
            print(f"[ONOS-POST] {url} → {resp.status_code}")
            return True
        except Exception as e:
            print(f"[ONOS ERROR] POST: {e}")
            return False

    def get_flow_path_stats(self, client_ip: str) -> Dict:
        """
        GET verso endpoint (da definire) che restituisce:
          { "n_paths": int, "n_violations": int }
        """

        url = f"http://localhost:8181/onos/v1/optimization/api/get/paths" #### cambiare
        try:

            return
        except Exception as e:
            print(f"[ONOS ERROR] GET path stats: {e}")
            return {"n_paths": 0, "n_violations": 0}

# ========== ACTIONS DI SET SLOT ==========
class ActionSetMovieSlot(Action):
    def name(self) -> Text:
        return "action_set_movie_slot"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        movie = next(tracker.get_latest_entity_values("movie"), None)
        if movie:
            return [SlotSet("movie", movie)]
        return []

class ActionSetQualitySlot(Action):
    def name(self) -> Text:
        return "action_set_quality_slot"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        quality = next(tracker.get_latest_entity_values("quality"), None)
        if quality:
            return [SlotSet("quality", quality)]
        return []

class ActionSetClientIpSlot(Action):
    def name(self) -> Text:
        return "action_set_client_ip_slot"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        client_ip = next(tracker.get_latest_entity_values("client_ip"), None)
        if client_ip:
            print(f"[CLIENT-IP] {client_ip}")
            return [SlotSet("client_ip", client_ip)]
        return []

# ========== ACTION: CALCOLA η_min DAL DIZIONARIO ==========
class ActionCalculateEtaMin(Action):
    def name(self) -> Text:
        return "action_calculate_eta_min"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        movie = tracker.get_slot("movie")
        quality = tracker.get_slot("quality")

        if not movie or not quality:
            dispatcher.utter_message("Error: movie or quality not set")
            return []

        eta_min = get_eta_min_from_dict(movie, quality)

        print(f"[CALCULATE] Movie={movie}, Quality={quality}, η_min={eta_min:.4f}")
        return [SlotSet("eta_min_threshold", eta_min)]

# ========== ACTION: INVIO A ONOS ==========
class ActionSendJsonToOnos(Action):
    def name(self) -> Text:
        return "action_send_json_to_onos"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        movie = tracker.get_slot("movie")
        quality = tracker.get_slot("quality")
        eta_min = tracker.get_slot("eta_min_threshold") or 1.0
        client_ip = tracker.get_slot("client_ip") or "0.0.0.0"

        if not movie or not quality or client_ip == "0.0.0.0":
            dispatcher.utter_message("Error: incomplete information!")
            return []

        throughput_mbps = quality_to_mbps(quality)

        json_data = {
            "id": f"intent_{int(time.time())}",
            "name": "video_streaming_request",
            "movie": movie,
            "quality": quality,
            "required_throughput": throughput_mbps,
            "eta_min": eta_min,
            "client_ip": client_ip
        }

        print("\n[SEND-TO-ONOS]")
        print(json.dumps(json_data, indent=2))

        client = ONOSClient()
        success = client.post_intent(json_data)

        if success:
            dispatcher.utter_message(f"Sent to ONOS with η_min={eta_min:.4f}")
        else:
            dispatcher.utter_message("Error sending to ONOS")

        return []

# ========== ACTION: AGGIORNAMENTO η_min IN BACKGROUND ==========
class ActionUpdateEtaMinBackground(Action):

    def name(self) -> Text:
        return "action_update_eta_min_background"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        movie = tracker.get_slot("movie")
        quality = tracker.get_slot("quality")
        client_ip = tracker.get_slot("client_ip") or "0.0.0.0"

        if not movie or not quality or client_ip == "0.0.0.0":
            return []

        # SCEGLI METODO: "ema" oppure "probabilistic"
        method = "ema"

        t = threading.Thread(
            target=self._background_update_eta_min,
            args=(movie, quality, client_ip, method),
            daemon=True
        )
        t.start()

        print(f"\n[BACKGROUND] η_min update thread started (method={method})")
        return []

    def _background_update_eta_min(self, movie: str, quality: str, client_ip: str, method: str):
        print(f"\n[BACKGROUND-THREAD] Starting, waiting 5s for ONOS measurements...")
        time.sleep(5)

        client = ONOSClient()

        for attempt in range(3):
            try:
                stats = client.get_flow_path_stats(client_ip) ### !!!!!!
                n_paths = stats.get("n_paths", 0)
                n_violations = stats.get("n_violations", 0)

                print(f"[BACKGROUND-THREAD] Attempt {attempt+1}/3")
                print(f"  n_paths={n_paths}, n_violations={n_violations}")

                if n_paths > 0:
                    if method == "ema":
                        new_eta = update_eta_min_ema(movie, quality, n_violations, n_paths, alpha=0.3)
                    elif method == "probabilistic":
                        new_eta = update_eta_min_probabilistic(movie, quality, n_violations, n_paths, alpha_blend=0.5)
                    else:
                        print(f"[ERROR] Unknown method: {method}")
                        return

                    update_eta_min_in_dict(movie, quality, new_eta)
                    print(f"[BACKGROUND-THREAD] η_min updated → {new_eta:.4f}")
                    return

                if attempt < 2:
                    print("[BACKGROUND-THREAD] No data yet, retry in 2s...")
                    time.sleep(2)

            except Exception as e:
                print(f"[BACKGROUND-THREAD ERROR] {e}")
                if attempt < 2:
                    time.sleep(2)

        print(f"[BACKGROUND-THREAD WARNING] Could not update η_min for client {client_ip}")
