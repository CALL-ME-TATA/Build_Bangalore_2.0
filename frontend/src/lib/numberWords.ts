// Amounts in words, shown under the tap answers of the doubt sheet ("₹340 / teen sau chaalis") so a
// confusable number can be told apart by how it sounds. Hindi in Latin letters, Indian place values.

const HI_0_99 = [
  'shunya', 'ek', 'do', 'teen', 'chaar', 'paanch', 'chhah', 'saat', 'aath', 'nau',
  'das', 'gyaarah', 'baarah', 'terah', 'chaudah', 'pandrah', 'solah', 'satrah', 'athaarah', 'unnees',
  'bees', 'ikkees', 'baais', 'teis', 'chaubees', 'pachchees', 'chhabbees', 'sattaais', 'atthaais', 'untees',
  'tees', 'iktees', 'battees', 'taintees', 'chauntees', 'paintees', 'chhattees', 'saintees', 'adtees', 'untaalees',
  'chaalis', 'iktaalees', 'bayaalees', 'taintaalees', 'chavaalees', 'paintaalees', 'chhiyaalees', 'saintaalees', 'adtaalees', 'unchaas',
  'pachaas', 'ikyaavan', 'baavan', 'tirepan', 'chauvan', 'pachpan', 'chhappan', 'sattaavan', 'atthaavan', 'unsath',
  'saath', 'iksath', 'baasath', 'tirsath', 'chausath', 'painsath', 'chhiyaasath', 'sadsath', 'adsath', 'unhattar',
  'sattar', 'ikhattar', 'bahattar', 'tihattar', 'chauhattar', 'pachhattar', 'chhihattar', 'sathattar', 'athhattar', 'unaasi',
  'assi', 'ikyaasi', 'bayaasi', 'tiraasi', 'chauraasi', 'pachaasi', 'chhiyaasi', 'sattaasi', 'athaasi', 'navaasi',
  'nabbe', 'ikyaanave', 'baanave', 'tiraanave', 'chauraanave', 'pachaanave', 'chhiyaanave', 'sattaanave', 'atthaanave', 'ninyaanave',
];

const EN_0_19 = [
  'zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine',
  'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen',
];
const EN_TENS = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety'];

function en99(n: number): string {
  if (n < 20) return EN_0_19[n] as string;
  const t = EN_TENS[Math.floor(n / 10)] as string;
  return n % 10 ? `${t}-${EN_0_19[n % 10]}` : t;
}

const hi99 = (n: number) => HI_0_99[n] as string;

/** Indian place values: crore, lakh, thousand, hundred, then 0-99. */
function build(n: number, small: (k: number) => string, names: [string, string, string, string]): string {
  if (n === 0) return small(0);
  const parts: string[] = [];
  const crore = Math.floor(n / 10000000);
  n %= 10000000;
  const lakh = Math.floor(n / 100000);
  n %= 100000;
  const thousand = Math.floor(n / 1000);
  n %= 1000;
  const hundred = Math.floor(n / 100);
  const rest = n % 100;
  if (crore) parts.push(`${crore < 100 ? small(crore) : build(crore, small, names)} ${names[0]}`);
  if (lakh) parts.push(`${small(lakh)} ${names[1]}`);
  if (thousand) parts.push(`${small(thousand)} ${names[2]}`);
  if (hundred) parts.push(`${small(hundred)} ${names[3]}`);
  if (rest) parts.push(small(rest));
  return parts.join(' ');
}

/** 340 -> "teen sau chaalis" (hi) / "three hundred forty" (en). Negative values use the absolute value. */
export function numberWords(value: number, lang: 'hi' | 'en' = 'hi'): string {
  const n = Math.abs(Math.round(Number(value) || 0));
  return lang === 'en'
    ? build(n, en99, ['crore', 'lakh', 'thousand', 'hundred'])
    : build(n, hi99, ['crore', 'lakh', 'hazaar', 'sau']);
}
