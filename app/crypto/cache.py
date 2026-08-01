import time


CACHE = {}

CACHE_SECONDS = 60


def get_cache(key):

    if key not in CACHE:
        return None


    item = CACHE[key]


    if time.time() - item["time"] > CACHE_SECONDS:
        del CACHE[key]
        return None


    return item["value"]



def set_cache(key, value):

    CACHE[key] = {
        "value": value,
        "time": time.time()
    }
