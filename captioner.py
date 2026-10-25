"""BLIP image captioning on the CPU."""
import os
import threading
import time

import torch
from PIL import Image
from transformers import BlipForConditionalGeneration, BlipProcessor

MODEL_NAME = os.environ.get("CAPTION_MODEL", "Salesforce/blip-image-captioning-base")
# torch would otherwise take every core; leave some for Streamlit, Prometheus and the OS.
TORCH_THREADS = int(os.environ.get("CAPTION_THREADS", "8"))
MAX_NEW_TOKENS = 30


class Captioner:
    def __init__(self):
        torch.set_num_threads(TORCH_THREADS)
        start = time.perf_counter()
        self.processor = BlipProcessor.from_pretrained(MODEL_NAME)
        self.model = BlipForConditionalGeneration.from_pretrained(MODEL_NAME).eval()
        self.load_seconds = time.perf_counter() - start
        # One image at a time through the model. Two Streamlit sessions calling
        # generate() together would fight over the same 8 threads and both get slower.
        self.lock = threading.Lock()

    def preprocess(self, image: Image.Image):
        return self.processor(images=image.convert("RGB"), return_tensors="pt")

    def generate(self, inputs) -> str:
        with torch.inference_mode():
            out = self.model.generate(**inputs, max_new_tokens=MAX_NEW_TOKENS)
        return self.processor.decode(out[0], skip_special_tokens=True).strip()
