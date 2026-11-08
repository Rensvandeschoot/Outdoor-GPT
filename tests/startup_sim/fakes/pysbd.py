import re


class Segmenter:
    def __init__(self, language='en', clean=False):
        pass

    def segment(self, text):
        parts = re.split(r'(?<=[.!?])\s+', text)
        return parts if parts else ['']
