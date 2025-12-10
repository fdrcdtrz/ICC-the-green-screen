from typing import Any, Text, Dict, List
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet
import requests, json

onos_controller_url = "http://192.168.31.1:8181/onos/v1"
username = "onos"
password = "rocks"

# -----------------------------
#  Mapping quality levels to Mbps

QUALITY_TO_MBPS = {
    "low": 2.5,
    "medium": 5,
    "high": 20
}

def quality_to_mbps(quality: str) -> float:
    q = quality.lower().strip()
    return QUALITY_TO_MBPS.get(q, 5)  # default = 5 Mbps, if no level matches with the qualitative ones handled


# -----------------------------
#  Placeholder for the semantic GRENNESS parameter

def compute_greenness(movie: str, quality: str) -> float:
    # something in the future, semantic model here
    return 0.75 # a dummy number


# -----------------------------
#  Placeholder for the triple-EFFICIENCY

def compute_efficiency(movie: str, quality: str) -> float:
    # updated with gian's function or similia
    return 0.60


# -----------------------------

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


class ActionSendJsonToOnos(Action):
    def name(self) -> Text:
        return "action_send_json_to_onos"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        movie = tracker.get_slot("movie")
        quality = tracker.get_slot("quality")

        if not movie or not quality:
            dispatcher.utter_message("Error: incomplete information!")
            return []

        # Quality → Mbps
        throughput_mbps = quality_to_mbps(quality)

        # Computing greenness and triple-efficiency
        greenness = compute_greenness(movie, quality)
        efficiency = compute_efficiency(movie, quality)

        dispatcher.utter_message(text=f"[DEBUG] Sending: movie={movie}, quality={quality} → {throughput_mbps} Mbps")

        # JSON
        json_data = {
            "id": "intent_4",
            "name": "new_video_streaming",
            "description": f"Video streaming '{movie}' with throughput level '{quality}' ({throughput_mbps} Mbps).",

            "required_throughput": throughput_mbps,

            "greenness": greenness,
            "efficiency": efficiency,

            "movie": movie
        }

        headers = {"Content-Type": "application/json"}

        try:
            response = requests.post(onos_controller_url, data=json.dumps(json_data), headers=headers, auth=(username, password))
            dispatcher.utter_message(text=f"Request sent! ONOS response: {response.status_code}")
        except Exception as e:
            dispatcher.utter_message(text=f"Error sending JSON: {e}")

        return []

