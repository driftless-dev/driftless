import os

from openai import OpenAI

MODEL = os.getenv("BRIEF_MODEL", "gpt-4o")
client = OpenAI
