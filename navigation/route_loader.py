import json

def load_route(route_file):
    with open(route_file, "r") as f:
        return json.load(f)