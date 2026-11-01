# Sarvam-language-voice-coach

**Bolo**: practise spoken English through role-play. When you get stuck, switch to your own language; the coach shows you the natural English and explains your mistakes in your language. Built on Sarvam AI (speech-to-text, chat, translation, text-to-speech).

## Run locally

```
pip install -r requirements.txt
echo SARVAM_API_KEY=your_key_here > .env
python app.py
```

Open http://127.0.0.1:5000 in Chrome or Edge.

## Deploy to Vercel

1. On vercel.com: **Add New → Project**, import this GitHub repo (no build settings needed; Vercel detects Flask).
2. Under **Environment Variables**, add:
   - `SARVAM_API_KEY`: your Sarvam key
   - `ACCESS_CODE` (optional but recommended): visitors must enter this code before the app uses your Sarvam credits
3. Deploy. The page lives in `public/` (served by Vercel's CDN); `app.py` runs as one Vercel Function.
