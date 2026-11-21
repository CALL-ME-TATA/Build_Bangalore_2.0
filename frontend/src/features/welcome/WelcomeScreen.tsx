// Landing page ("#/welcome"): one audience (kirana shopkeepers), one action (sign in with Google, or open the
// khata when sign-in is not configured). Every number on it is measured (README: latency, noise test); there
// are no invented testimonials. In-page links scroll with buttons, because the router owns the URL hash.
import { Link } from '@tanstack/react-router';
import { ArrowRight, AudioLines, CircleHelp, History, Languages, Lock, Mic, ShieldCheck, Volume2 } from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Amount } from '../../components/Amount';
import { LOGIN_URL, useAuth } from '../../services/auth';

const ease = 'ease-[cubic-bezier(0.22,1,0.36,1)]';

function scrollTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
}

/** Rise 32px and fade in once, when the section first enters the viewport. */
function Reveal({ children, className = '' }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => {
      if (e?.isIntersecting) {
        setShown(true);
        io.disconnect();
      }
    }, { rootMargin: '0px 0px -10% 0px' });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return (
    <div ref={ref} data-shown={shown || undefined} className={`kv-reveal ${className}`}>
      {children}
    </div>
  );
}

/** The primary action: Google sign-in when the server has it, else straight into the khata. */
function PrimaryAction({ size = 'lg' }: { size?: 'md' | 'lg' }) {
  const { data } = useAuth();
  const cls = `inline-flex min-h-12 shrink-0 items-center whitespace-nowrap justify-center gap-2 rounded-control bg-accent px-5 font-medium text-on-accent transition-[filter,transform] duration-300 ${ease} hover:brightness-95 active:scale-[0.98] ${size === 'lg' ? 'text-label' : 'text-label-sm'}`;
  if (data?.enabled && !data.user) {
    return (
      <a href={LOGIN_URL} className={cls}>
        <GoogleMark />
        {size === 'md' ? (
          // The top bar is narrow on a phone: "Login" there, the full words from 640px up and in the hero.
          <>
            <span className="sm:hidden">Login</span>
            <span className="hidden sm:inline">Google se login karein</span>
          </>
        ) : (
          'Google se login karein'
        )}
      </a>
    );
  }
  return (
    <Link to="/" className={cls}>
      Khata kholiye
      <ArrowRight aria-hidden="true" size={20} strokeWidth={1.8} />
    </Link>
  );
}

function GoogleMark() {
  // The Google "G" drawn in the button's own colour (one accent per screen; no brand colours on the accent).
  return (
    <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
      <path d="M20.5 12.2c0-.6-.1-1.2-.2-1.8H12v3.5h4.8a4.4 4.4 0 0 1-1.9 2.8" />
      <path d="M14.9 16.7A6.5 6.5 0 1 1 16.4 7.4" />
    </svg>
  );
}

/** Under the hero button: who can open the khata (only when Google sign-in is on). */
function AccessNote() {
  const { data } = useAuth();
  if (!data?.enabled) return null;
  return (
    <span className="flex items-center gap-2 text-small text-ink-2">
      <Lock aria-hidden="true" size={16} strokeWidth={1.7} />
      {data.user ? `Login: ${data.user.email}` : 'Google account se; har account ka apna khata'}
    </span>
  );
}

function LoginNotice({ login }: { login?: string }) {
  if (login !== 'not_allowed' && login !== 'failed') return null;
  const text = login === 'not_allowed'
    ? 'Is Google account ko is dukaan ka khata kholne ki anumati nahi hai. Dukaan ke maalik se apna email ALLOWED_EMAILS mein judwaiye.'
    : 'Login poora nahi hua. Dobara koshish kijiye.';
  return (
    <p role="alert" className="mx-auto mb-6 max-w-[42rem] rounded-control border border-line-strong bg-surface px-4 py-3 text-small text-ink">
      {text}
    </p>
  );
}

// ---- hero visual: the real ledger look (speech, spoken reply, ruled entry row, one doubt question) -----------
function HeroVisual() {
  return (
    <figure aria-label="KhataVaani mein ek baatcheet ka udaharan" className="w-full rounded-sheet-lg border border-line bg-surface p-6 shadow-float">
      <div className="flex justify-end">
        <p className="max-w-bubble rounded-sheet bg-tint px-4 py-3 text-body text-ink">“Ramesh ka teen sau chaalis udhaar”</p>
      </div>
      <p className="mt-4 flex items-start gap-2 text-body text-ink">
        <Volume2 aria-hidden="true" size={18} strokeWidth={1.7} className="mt-1 shrink-0 text-ink-2" />
        Ramesh ke khate mein ₹340 udhaar likh diya.
      </p>
      <div className="mt-6 grid grid-cols-[var(--spacing-amount)_1fr_auto] items-baseline gap-3 border-y border-line py-3">
        <Amount value={340} kind="credit" tone size="lg" lang="hi" className="text-end" />
        <span className="text-label-sm text-ink">Udhaar · Ramesh</span>
        <span className="text-meta text-ink-2">Aaj, 11:42</span>
      </div>
      <div className="mt-6 rounded-sheet bg-fill p-4">
        <p className="text-eyebrow uppercase text-ask">Shor zyada tha, isliye poochha</p>
        <p className="mt-2 font-display text-title-sm text-ink">₹340 ya ₹740?</p>
        <div className="mt-3 grid grid-cols-2 gap-2">
          <span className="rounded-control border border-line-strong bg-surface px-3 py-2 text-center text-label-sm text-ink">₹340</span>
          <span className="rounded-control border border-line-strong bg-surface px-3 py-2 text-center text-label-sm text-ink">₹740</span>
        </div>
      </div>
      <figcaption className="sr-only">
        Dukaandaar bolta hai Ramesh ka 340 udhaar. KhataVaani likhkar sunata hai, aur shor mein pakka karne ke liye poochta hai 340 ya 740.
      </figcaption>
    </figure>
  );
}

// ---- tagline: each word goes from muted to full ink as it crosses the middle of the screen ------------------
function TaglineReveal({ lines }: { lines: string[] }) {
  const ref = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    const words = Array.from(root.querySelectorAll<HTMLElement>('[data-word]'));
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
      words.forEach((w) => w.setAttribute('data-on', ''));
      return;
    }
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (e.isIntersecting) {
          e.target.setAttribute('data-on', '');
          io.unobserve(e.target);
        }
      }
    }, { rootMargin: '0px 0px -45% 0px' });
    words.forEach((w) => io.observe(w));
    return () => io.disconnect();
  }, []);
  return (
    <p ref={ref} className="mx-auto max-w-[42.5rem] text-balance font-display text-title-md text-ink sm:text-title-lg lg:text-hero">
      {lines.map((line, i) => (
        <span key={i} className="block">
          {line.split(' ').map((w, j) => (
            <span key={j} data-word className="kv-word">
              {w}{' '}
            </span>
          ))}
        </span>
      ))}
    </p>
  );
}

const BENEFITS = [
  { icon: Mic, title: 'Haath bhare hon, tab bhi khata likha jaaye', body: 'Button dabaiye aur ek line boliye. Do entry ek saath bhi: “Ramesh ka 340 udhaar, kal 200 diya tha”.' },
  { icon: CircleHelp, title: 'Shak ho to sawaal, galti nahi', body: 'Jab pakka nahi hota, ek chhota sawaal poochta hai, jaise “340 ya 740?”. Aapke haan kehne tak kuch save nahi hota.' },
  { icon: History, title: 'Har badlaav dikhta hai', body: '“Nahi, 430” bolne par purani entry kat kar dikhti hai, mitti nahi. Jhagde ke waqt poora hisaab saamne hai.' },
  { icon: AudioLines, title: 'Shor wali dukaan mein bhi', body: 'Bahut shor ho to entry padh kar sunata hai aur haan ke baad hi likhta hai.' },
];

const STEPS = [
  { title: 'Button dabaiye, boliye', body: 'Hindi, Hinglish ya English mein: “Sunita ne paanch sau diye”.' },
  { title: 'KhataVaani likhkar sunata hai', body: '“Sunita se ₹500 mile, jama kar diya.” Screen par nayi entry turant.' },
  { title: 'Shak ho to ek sawaal', body: '“Aap kaunse Diwakar ki baat kar rahe hain?” Jawab dijiye, phir save.' },
];

const PROOF = [
  { value: '0.24 se 0.70 s', label: 'bolna khatam hone se pehli awaaz tak, asli Gnani services ke saath maapa gaya' },
  { value: '0 galat entry', label: '120 shor wale test turns mein, safed, gulabi aur logon ki awaaz wale shor ke saath' },
  { value: 'Encrypted', label: 'har naam aur rakam AES GCM se band, aur koi entry kabhi mitai nahi jaati' },
];

const FAQ = [
  { id: 'faq-ai', q: 'Kya yeh AI hai?', a: 'Haan. Har session ki pehli line mein KhataVaani khud batata hai ki woh ek AI sahayak hai.' },
  { id: 'faq-wrong', q: 'Agar galat sun liya to?', a: 'Jab pakka nahi hota, woh poochta hai. Save hone ke baad galti dikhe to “Nahi, 430” boliye, ya “undo karo” se pichli entry hata dijiye.' },
  { id: 'faq-lang', q: 'Kaunsi bhasha chalti hai?', a: 'Hindi, Hinglish aur English. Rakam shabdon mein bhi chalti hai: dedh sau, dhai hazaar, saadhe teen sau.' },
  { id: 'faq-names', q: 'Ek naam ke do grahak hon to?', a: 'Woh poochta hai: “Aap kaunse Diwakar ki baat kar rahe hain: Diwakar, Diwakar Sharma ya koi aur?” Naye grahak ki pehchaan bhi poochta hai, jaise chai wale.' },
  { id: 'faq-data', q: 'Mera data kahan rehta hai?', a: 'Aapke apne server par, encrypted. Login Google account se hota hai, aur har account ka khata alag rehta hai: koi doosre ka khata nahi dekh sakta. Har sudhaar nayi entry ke roop mein judta hai, purani entry kabhi nahi mitti.' },
  { id: 'faq-net', q: 'Internet chala jaaye to?', a: 'Bolne ke liye internet chahiye. Bina internet ke type ki hui lines phone par encrypted rehti hain aur net aate hi save hoti hain.' },
  { id: 'faq-remind', q: 'Grahak ko reminder kaise jaata hai?', a: 'SMS se, aur sirf un grahakon ko jinhone haan kaha ho, jab aap “Reminder bhejein” dabayein. Ek grahak ko din mein ek hi SMS jaata hai. Apne aap kuch nahi jaata.' },
];

export function WelcomeScreen({ login }: { login?: string }) {
  useEffect(() => {
    const prev = document.title;
    document.title = 'KhataVaani: bolkar likhiye udhaar ka khata';
    return () => {
      document.title = prev;
    };
  }, []);

  return (
    <div className="min-h-dvh bg-paper text-ink">
      {/* Floating bar, sized to its content; solid surface (the design system has no glass or blur). */}
      <header className="sticky top-4 z-30 px-4">
        <nav aria-label="Landing" className="mx-auto flex max-w-[64rem] items-center justify-between gap-4 rounded-control border border-line bg-surface px-4 py-2 shadow-float">
          <span className="whitespace-nowrap font-display text-title-sm text-ink">KhataVaani</span>
          <div className="hidden items-center gap-1 sm:flex">
            {[['kaise', 'Kaise kaam karta hai'], ['bharosa', 'Bharosa'], ['sawaal', 'Sawaal']].map(([id, label]) => (
              <button key={id} type="button" onClick={() => scrollTo(id!)} className={`min-h-12 rounded-nav px-3 text-label-sm text-ink-2 transition-colors duration-300 ${ease} hover:bg-tint hover:text-ink`}>
                {label}
              </button>
            ))}
          </div>
          <PrimaryAction size="md" />
        </nav>
      </header>

      <main id="main" tabIndex={-1} className="px-4 outline-none">
        {/* Hero */}
        <section aria-labelledby="hero-title" className="mx-auto grid max-w-[64rem] items-center gap-12 pt-16 pb-24 lg:grid-cols-[1.1fr_1fr] lg:pt-24">
          <div>
            <LoginNotice login={login} />
            <p className="text-eyebrow uppercase text-ink-2">Kirana dukaan ke liye udhaar khata</p>
            <h1 id="hero-title" className="mt-4 max-w-[42.5rem] text-balance font-display text-title-lg text-ink lg:text-hero">
              Bolo,
              <br />
              khata likh jaayega.
            </h1>
            <p className="mt-6 max-w-[42.5rem] text-pretty text-body-lg text-ink-2">
              “Ramesh ka 340 udhaar” boliye. KhataVaani likhta hai, bolkar sunata hai, aur shak ho to pehle poochta hai.
              Kaagaz, pen aur typing ki zaroorat nahi.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-4">
              <PrimaryAction />
              <AccessNote />
            </div>
            <p className="mt-8 text-small text-ink-2">
              Pehli awaaz <span className="text-ink">0.24 se 0.70 second</span> mein · Gnani Prisma aur Timbre par bana
            </p>
          </div>
          <HeroVisual />
        </section>

        {/* Problem to solution */}
        <Reveal className="mx-auto max-w-[64rem] border-t border-line py-24">
          <section aria-labelledby="problem-title" className="grid gap-12 lg:grid-cols-2">
            <h2 id="problem-title" className="text-balance font-display text-title-md text-ink lg:text-title-lg">
              Kaagaz ka khata bheed mein peeche chhoot jaata hai.
            </h2>
            <div className="flex flex-col gap-6 text-body text-ink-2">
              <p className="text-pretty">
                Counter par paanch grahak khade hain, ek haath mein saamaan, doosre mein chhutta. Udhaar likhne ka waqt nahi milta,
                aur shaam ko yaad nahi rehta ki kisne kitna liya. Phir mahine ke aakhir mein “maine itna nahi liya” wala jhagda.
              </p>
              <p className="text-pretty text-ink">
                KhataVaani mein ek line bolna kaafi hai. Entry usi pal likhi jaati hai, aapko sunai deti hai, aur har sudhaar ka
                record rehta hai.
              </p>
            </div>
          </section>
        </Reveal>

        {/* Benefits */}
        <Reveal className="mx-auto max-w-[64rem] pb-24">
          <section aria-labelledby="benefits-title">
            <h2 id="benefits-title" className="text-eyebrow uppercase text-ink-2">Kya milta hai</h2>
            <ul className="mt-8 grid gap-x-12 gap-y-10 sm:grid-cols-2">
              {BENEFITS.map(({ icon: Icon, title, body }) => (
                <li key={title} className="flex gap-4">
                  <Icon aria-hidden="true" size={24} strokeWidth={1.6} className="mt-1 shrink-0 text-ink-2" />
                  <div>
                    <h3 className="text-label text-ink">{title}</h3>
                    <p className="mt-2 text-pretty text-body text-ink-2">{body}</p>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        </Reveal>

        {/* Tagline reveal */}
        <section aria-label="KhataVaani ka vaada" className="mx-auto max-w-[64rem] border-t border-line py-24 text-center">
          <TaglineReveal lines={['Aap boliye, KhataVaani likhega.', 'Pakka hone tak kuch save nahi hoga.']} />
        </section>

        {/* How it works */}
        <Reveal className="mx-auto max-w-[64rem] border-t border-line py-24">
          <section id="kaise" aria-labelledby="how-title" className="scroll-mt-24">
            <h2 id="how-title" className="font-display text-title-md text-ink lg:text-title-lg">Teen kadam</h2>
            <ol className="mt-12 grid gap-10 sm:grid-cols-3">
              {STEPS.map((s, i) => (
                <li key={s.title}>
                  <span aria-hidden="true" className="font-display text-total text-ink-2">{i + 1}</span>
                  <h3 className="mt-3 text-label text-ink">{s.title}</h3>
                  <p className="mt-2 text-pretty text-body text-ink-2">{s.body}</p>
                </li>
              ))}
            </ol>
            <p className="mt-12 text-body text-ink-2">
              Pehle dekhna hai?{' '}
              <Link to="/demo" className="text-ink underline underline-offset-4 hover:no-underline">
                Bina login ke demo chalaiye
              </Link>
              .
            </p>
          </section>
        </Reveal>

        {/* Proof: measured numbers only */}
        <Reveal className="mx-auto max-w-[64rem] border-t border-line py-24">
          <section id="bharosa" aria-labelledby="proof-title" className="scroll-mt-24">
            <h2 id="proof-title" className="flex items-center gap-3 font-display text-title-md text-ink lg:text-title-lg">
              <ShieldCheck aria-hidden="true" size={28} strokeWidth={1.6} className="text-ink-2" />
              Naapa gaya, likha gaya
            </h2>
            <dl className="mt-12 grid gap-10 sm:grid-cols-3">
              {PROOF.map((p) => (
                <div key={p.value} className="border-t border-line-strong pt-4">
                  <dt className="font-display text-total text-ink">{p.value}</dt>
                  <dd className="mt-2 text-pretty text-small text-ink-2">{p.label}</dd>
                </div>
              ))}
            </dl>
            <p className="mt-10 flex items-center gap-2 text-small text-ink-2">
              <Languages aria-hidden="true" size={16} strokeWidth={1.7} />
              Recorded awaaz se laptop par maapa gaya, 21 November 2026. Asli dukaan mein phone par abhi naapna baaki hai.
            </p>
          </section>
        </Reveal>

        {/* FAQ */}
        <Reveal className="mx-auto max-w-[48rem] border-t border-line py-24">
          <section id="sawaal" aria-labelledby="faq-title" className="scroll-mt-24">
            <h2 id="faq-title" className="font-display text-title-md text-ink lg:text-title-lg">Aksar poochhe jaane wale sawaal</h2>
            <div className="mt-10 divide-y divide-line border-y border-line">
              {FAQ.map((f) => (
                <details key={f.id} id={f.id} className="group scroll-mt-24 py-2">
                  <summary className="flex min-h-12 cursor-pointer list-none items-center justify-between gap-4 text-label text-ink">
                    {f.q}
                    <span aria-hidden="true" className={`text-ink-2 transition-transform duration-300 ${ease} group-open:rotate-45`}>+</span>
                  </summary>
                  <p className="pb-4 text-pretty text-body text-ink-2">{f.a}</p>
                </details>
              ))}
            </div>
          </section>
        </Reveal>

        {/* Final CTA, identical to the top */}
        <Reveal className="mx-auto max-w-[64rem] py-24 text-center">
          <section aria-labelledby="final-title">
            <h2 id="final-title" className="mx-auto max-w-[42.5rem] text-balance font-display text-title-md text-ink lg:text-title-lg">
              Aaj ka udhaar, aaj hi bolkar likhiye.
            </h2>
            <p className="mx-auto mt-4 max-w-[42.5rem] text-pretty text-body text-ink-2">
              Har entry save hone se pehle aapko sunai deti hai, aur “undo karo” se pichli entry turant hat jaati hai.
            </p>
            <div className="mt-8 flex justify-center">
              <PrimaryAction />
            </div>
          </section>
        </Reveal>
      </main>

      <footer className="border-t border-line px-4 py-10">
        <div className="mx-auto flex max-w-[64rem] flex-wrap items-center justify-between gap-4 text-small text-ink-2">
          <span>
            <span className="font-display text-ink">KhataVaani</span> · Gnani API Platform par bana
          </span>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => { scrollTo('faq-data'); (document.getElementById('faq-data') as HTMLDetailsElement | null)?.setAttribute('open', ''); }} className="min-h-12 rounded-nav px-3 hover:bg-tint hover:text-ink">
              Data aur privacy
            </button>
            <Link to="/demo" className="inline-flex min-h-12 items-center rounded-nav px-3 hover:bg-tint hover:text-ink">
              Demo
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
