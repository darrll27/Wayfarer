import fnmatch
from typing import List, Dict

class RouteTable:
    def __init__(self, routes: List[Dict[str, str]]):
        self.routes = routes

    def outputs_for(self, origin_name: str) -> List[str]:
        outs = []
        for r in self.routes:
            if fnmatch.fnmatch(origin_name, r["from"]):
                outs.append(r["to"])
        return outs
