// Fixed UI labels in the two reply languages: "hi" (Hindi / Hinglish) and "en" (English).

const STRINGS = {
  hi: {
    ai: 'AI sahayak',
    aiTitle: 'Yeh ek AI hai, insaan nahi',
    reconnecting: 'Dobara jud raha hai…',
    listening: 'Sun raha hoon…',
    hearing: 'Aawaz aa rahi hai…',
    transcribing: 'Samajh raha hoon…',
    thinking: 'Soch raha hoon…',
    speaking: 'Bol raha hoon…',
    idle: 'Dabakar boliye',
    question: 'Sawaal',
    hint: 'DABAKAR BOLIYE',
    micDenied: 'Microphone ki ijaazat nahi mili. Type karein se bhi test kar sakte hain.',
    micFail: 'Microphone nahi chala (HTTPS chahiye). Type karein se test karein.',
    typeLabel: 'Type karein',
    send: 'Bhejein',
    removed: 'hataya',
    noConn: 'Connection nahi hai, dobara dabaiye',
    transcript: 'LIVE TRANSCRIPT',
    tabTalk: 'Baat',
    tabLedger: 'Khata',
    khataTitle: 'Aaj ka Khata',
    creditGiven: 'Udhaar diya',
    paymentIn: 'Payment aaya',
    customers: 'Grahak',
    recent: 'Haal ki entries',
    tagline: 'Aapka voice khata. Main ek AI sahayak hoon.',
  },
  en: {
    ai: 'AI assistant',
    aiTitle: 'This is an AI, not a person',
    reconnecting: 'Reconnecting…',
    listening: 'Listening…',
    hearing: 'Hearing…',
    transcribing: 'Transcribing…',
    thinking: 'Thinking…',
    speaking: 'Speaking…',
    idle: 'Hold to talk',
    question: 'Question',
    hint: 'HOLD TO TALK',
    micDenied: 'Microphone permission was not granted. You can still test with the Type box.',
    micFail: 'The microphone did not start (HTTPS is required). Test with the Type box.',
    typeLabel: 'Type instead',
    send: 'Send',
    removed: 'removed',
    noConn: 'No connection, press again',
    transcript: 'LIVE TRANSCRIPT',
    tabTalk: 'Talk',
    tabLedger: 'Ledger',
    khataTitle: "Today's Khata",
    creditGiven: 'Credit given',
    paymentIn: 'Payments received',
    customers: 'Customers',
    recent: 'Recent entries',
    tagline: 'Your voice ledger. I am an AI assistant.',
  },
};

export const LANGS = ['hi', 'en'];

/** Label for `key` in `lang`; unknown languages fall back to Hindi. */
export function t(lang, key) {
  return (STRINGS[lang] || STRINGS.hi)[key];
}

export function normalizeLang(v) {
  return v === 'en' ? 'en' : 'hi';
}
