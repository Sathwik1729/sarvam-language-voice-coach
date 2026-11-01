"""Bolo: an English speaking coach that explains in your own language.

Run:  python app.py   then open http://127.0.0.1:5000
"""
import hmac
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from sarvamai import SarvamAI
from werkzeug.exceptions import HTTPException

HERE = Path(__file__).parent

# Load SARVAM_API_KEY from .env (no extra dependency needed)
env_file = HERE / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() and not key.strip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip())

if not os.environ.get("SARVAM_API_KEY"):
    raise SystemExit("SARVAM_API_KEY is not set. Add it to .env (local) or the Vercel project's Environment Variables.")

client = SarvamAI(api_subscription_key=os.environ["SARVAM_API_KEY"])
# Optional: if set, visitors must enter this code before the app calls Sarvam (protects your credits)
ACCESS_CODE = os.environ.get("ACCESS_CODE", "")
PUBLIC_DIR = HERE / "public"  # Vercel serves this folder from its CDN; Flask serves it locally
app = Flask(__name__, static_folder=None)

CHAT_MODEL = "sarvam-105b-conversations"
STT_MODEL = "saaras:v4"
TTS_MODEL = "bulbul:v3"
VOICE = "shubh"

# Helper languages: ones that both speech-to-text and text-to-speech support
LANGUAGES = {
    "hi-IN": "Hindi", "bn-IN": "Bengali", "ta-IN": "Tamil", "te-IN": "Telugu",
    "kn-IN": "Kannada", "ml-IN": "Malayalam", "mr-IN": "Marathi",
    "gu-IN": "Gujarati", "pa-IN": "Punjabi", "od-IN": "Odia",
}

SCENARIOS = {
    "interview": "a job interview for an entry-level office role. You are the interviewer.",
    "intro": "a friendly first meeting where the learner introduces themselves. You are a new colleague.",
    "restaurant": "ordering food at a restaurant. You are the waiter.",
    "doctor": "a visit to a doctor's clinic. You are the receptionist, then the doctor.",
    "customer_care": "a phone call to customer care about a wrong mobile bill. You are the support agent.",
    "bank": "opening a savings account at a bank. You are the bank officer.",
}

# The chat model writes English only; the translation API turns the teaching
# into the learner's language (this gives much better Indic text than asking
# the chat model for Indic text inside JSON).
SYSTEM_PROMPT = """You are Bolo, a warm, patient English speaking coach for Indian learners.
You are role-playing {scenario}
The learner's own language is {lang}. They may speak English, {lang}, or a mix when they get stuck,
so their message can contain {lang} words in {lang} script.

For each learner message, reply ONLY with a JSON object with these keys, all written in English:
- "english_version": what the learner meant, as natural, correct, simple English (translate any {lang} parts).
- "used_own_language": true if the message contains any {lang} words, else false.
- "feedback": at most 2 corrections of the learner's own English (not of {lang} parts), most useful first,
  each one about a different mistake. Each item is
  {{"you_said": the learner's exact words, "better": a natural English version, "why": one short, kind sentence explaining the rule in very simple English}}.
  Use an empty list if their English was fine. Ignore punctuation and small transcription glitches.
- "score": 1 to 5 for how clear and correct their English was (5 = perfect; 1 if they spoke only {lang}).
- "reply": your next line in the role-play, in simple spoken English, 1 to 3 short sentences, ending with a question that keeps the conversation going.

If the message is "<START>", greet the learner in character and ask the first question,
with "english_version" "", "used_own_language" false, "feedback" [] and "score" 0.
Never break character in "reply". Put all teaching in "feedback"."""

pool = ThreadPoolExecutor(max_workers=8)


def translate(text: str, lang: str) -> str:
    """English -> learner's language, in the casual mixed style people actually speak."""
    try:
        res = client.text.translate(input=text, source_language_code="en-IN", target_language_code=lang,
                                    model="mayura:v1", mode="modern-colloquial")
    except Exception:  # language not supported by Mayura: use the formal model instead
        res = client.text.translate(input=text, source_language_code="en-IN", target_language_code=lang,
                                    model="sarvam-translate:v1")
    return res.translated_text


def tts(text: str, lang: str) -> str:
    """Return base64 WAV audio for text."""
    res = client.text_to_speech.convert(
        text=text[:2500], language_code=lang, speaker=VOICE, model=TTS_MODEL
    )
    return res.audios[0]


@app.before_request
def check_access_code():
    if ACCESS_CODE and request.path.startswith("/api/") and request.path != "/api/options":
        given = request.headers.get("X-Access-Code", "")
        if not hmac.compare_digest(given.encode(), ACCESS_CODE.encode()):
            return jsonify(error="Wrong or missing access code.", need_code=True), 401


@app.get("/")
def index():
    return send_from_directory(PUBLIC_DIR, "index.html")


@app.get("/api/options")
def options():
    return jsonify(languages=LANGUAGES, scenarios=list(SCENARIOS), needs_code=bool(ACCESS_CODE))


@app.post("/api/turn")
def turn():
    lang_code = request.form.get("lang", "hi-IN")
    scenario = request.form.get("scenario", "intro")
    if lang_code not in LANGUAGES or scenario not in SCENARIOS:
        return jsonify(error="Unknown language or scenario."), 400
    history = json.loads(request.form.get("history", "[]"))[-12:]

    # 1. What did the learner say? (voice -> text, keeps code-mixed speech as spoken)
    transcript = request.form.get("text", "").strip()
    audio = request.files.get("audio")
    if audio:
        stt = client.speech_to_text.transcribe(
            file=(audio.filename or "speech.webm", audio.read(), audio.mimetype),
            model=STT_MODEL,
            mode="codemix",
            language_code=lang_code,  # auto-detect turns mixed speech into English
        )
        transcript = (stt.transcript or "").strip()
        if not transcript:
            return jsonify(error="I couldn't hear anything. Try again, a bit closer to the mic."), 422
    if not transcript:
        transcript = "<START>"

    # 2. Coach: correct, explain in the learner's language, continue the role-play
    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(
        scenario=SCENARIOS[scenario], lang=LANGUAGES[lang_code])}]
    messages += [{"role": m["role"], "content": m["content"]} for m in history
                 if m.get("role") in ("user", "assistant") and m.get("content")]
    messages.append({"role": "user", "content": transcript})

    res = client.chat.completions(
        model=CHAT_MODEL, messages=messages, response_format={"type": "json_object"}
    )
    try:
        coach = json.loads(res.choices[0].message.content)
    except (json.JSONDecodeError, TypeError):
        return jsonify(error="The coach got confused. Please say that again."), 502

    reply = coach.get("reply") or "Could you say that again?"
    coach["reply"] = reply

    # Drop duplicate corrections
    seen, feedback = set(), []
    for f in coach.get("feedback") or []:
        if isinstance(f, dict) and f.get("better") and f["better"] not in seen:
            seen.add(f["better"])
            feedback.append(f)
    coach["feedback"] = feedback[:2]

    # 3. In parallel: speak the reply, translate it, explain each correction in the learner's language
    audio_job = pool.submit(tts, reply, "en-IN")
    reply_job = pool.submit(translate, reply, lang_code)
    why_jobs = [pool.submit(translate, f.get("why", ""), lang_code) if f.get("why") else None
                for f in feedback]
    coach["reply_translation"] = reply_job.result()
    for f, job in zip(coach["feedback"], why_jobs):
        f["why_native"] = job.result() if job else ""

    return jsonify(
        transcript="" if transcript == "<START>" else transcript,
        coach=coach,
        audio=audio_job.result(),
    )


@app.post("/api/speak")
def speak():
    """Read a short explanation aloud in the learner's language."""
    data = request.get_json(force=True)
    lang_code = data.get("lang", "en-IN")
    if lang_code not in LANGUAGES and lang_code != "en-IN":
        return jsonify(error="Unknown language."), 400
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify(error="Nothing to read."), 400
    return jsonify(audio=tts(text, lang_code))


@app.errorhandler(Exception)
def on_error(e):
    if isinstance(e, HTTPException):
        return e
    app.logger.exception(e)
    return jsonify(error="Something went wrong talking to Sarvam. Please try again."), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
