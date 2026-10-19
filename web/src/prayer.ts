// Prayer times, worked out from where you are: the sun's position for the day (the usual
// astronomical formulas), the angle below the horizon each method uses for Fajr and Isha, and the
// shadow length for Asr (Hanafi: twice the object's height, the others: once).
// Everything is computed here, in the browser, so it works without any outside service.

export type PrayerName = "fajr" | "sunrise" | "dhuhr" | "asr" | "maghrib" | "isha";
export const PRAYERS: PrayerName[] = ["fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha"];
/** The five daily prayers (sunrise isn't one). */
export const FARD: Exclude<PrayerName, "sunrise">[] = ["fajr", "dhuhr", "asr", "maghrib", "isha"];

export type Method = "karachi" | "mwl" | "isna" | "makkah" | "egypt" | "dubai" | "singapore" | "turkey" | "tehran" | "jafari";
export type HighLat = "angle" | "midnight" | "seventh" | "none";

interface MethodSpec {
  fajr: number;               // degrees below the horizon
  isha: number | { minutes: number };
  maghrib?: number;           // degrees, when Maghrib isn't sunset
  label: string;
}

export const METHODS: Record<Method, MethodSpec> = {
  karachi: { fajr: 18, isha: 18, label: "University of Islamic Sciences, Karachi (Bangladesh, Pakistan, India)" },
  mwl: { fajr: 18, isha: 17, label: "Muslim World League (Europe, Far East)" },
  isna: { fajr: 15, isha: 15, label: "Islamic Society of North America" },
  makkah: { fajr: 18.5, isha: { minutes: 90 }, label: "Umm al-Qura, Makkah" },
  egypt: { fajr: 19.5, isha: 17.5, label: "Egyptian General Authority of Survey" },
  dubai: { fajr: 18.2, isha: 18.2, label: "Dubai (Gulf)" },
  singapore: { fajr: 20, isha: 18, label: "Singapore, Malaysia, Indonesia" },
  turkey: { fajr: 18, isha: 17, label: "Diyanet, Turkey" },
  tehran: { fajr: 17.7, isha: 14, maghrib: 4.5, label: "Institute of Geophysics, Tehran" },
  jafari: { fajr: 16, isha: 14, maghrib: 4, label: "Shia Ithna Ashari (Jafari)" },
};

export interface PrayerSettings {
  lat: number | null; lng: number | null; place: string; timezone: string | null;
  method: Method; asr: "hanafi" | "standard"; high_lat: HighLat;
  offsets: Record<PrayerName, number>;
  reminders: { fajr: boolean; dhuhr: boolean; asr: boolean; maghrib: boolean; isha: boolean; before: number; jamaah_note: boolean };
}

export type DayTimes = Record<PrayerName, Date> & { midnight: Date; lastThird: Date };

// ------------------------------------------------------------------ the sun

const rad = (d: number) => (d * Math.PI) / 180;
const deg = (r: number) => (r * 180) / Math.PI;
const sin = (d: number) => Math.sin(rad(d));
const cos = (d: number) => Math.cos(rad(d));
const tan = (d: number) => Math.tan(rad(d));
const asin = (x: number) => deg(Math.asin(x));
const acos = (x: number) => deg(Math.acos(x));
const atan2 = (y: number, x: number) => deg(Math.atan2(y, x));
const acot = (x: number) => deg(Math.atan(1 / x));
const fix = (a: number, b: number) => { const r = a - b * Math.floor(a / b); return r < 0 ? r + b : r; };

function julian(y: number, m: number, d: number): number {
  if (m <= 2) { y -= 1; m += 12; }
  const a = Math.floor(y / 100), b = 2 - a + Math.floor(a / 4);
  return Math.floor(365.25 * (y + 4716)) + Math.floor(30.6001 * (m + 1)) + d + b - 1524.5;
}

/** Declination of the sun and the equation of time, for a Julian date. */
function sun(jd: number): { decl: number; eqt: number } {
  const D = jd - 2451545.0;
  const g = fix(357.529 + 0.98560028 * D, 360);
  const q = fix(280.459 + 0.98564736 * D, 360);
  const L = fix(q + 1.915 * sin(g) + 0.02 * sin(2 * g), 360);
  const e = 23.439 - 0.00000036 * D;
  const ra = fix(atan2(cos(e) * sin(L), cos(L)) / 15, 24);
  return { decl: asin(sin(e) * sin(L)), eqt: q / 15 - ra };
}

/**
 * Times for one calendar day at a place, as real moments (Date). `y, m, d` is the date where the
 * place is. Unknown times (the sun never gets that low, far north in summer) are adjusted by the
 * high-latitude rule.
 */
export function prayerTimes(y: number, m: number, d: number, s: Pick<PrayerSettings, "lat" | "lng" | "method" | "asr" | "high_lat" | "offsets">): DayTimes {
  const lat = s.lat ?? 0, lng = s.lng ?? 0;
  const spec = METHODS[s.method] ?? METHODS.karachi;
  const jd0 = julian(y, m, d) - lng / (15 * 24);
  const factor = s.asr === "hanafi" ? 2 : 1;

  // times as hours of local solar day; refined twice with the sun's position at that moment
  const midDay = (t: number) => fix(12 - sun(jd0 + t / 24).eqt, 24);
  const angleTime = (angle: number, t: number, before: boolean) => {
    const { decl } = sun(jd0 + t / 24);
    const noon = midDay(t);
    const h = acos((-sin(angle) - sin(decl) * sin(lat)) / (cos(decl) * cos(lat))) / 15;
    return noon + (before ? -h : h);
  };
  const asrTime = (t: number) => {
    const { decl } = sun(jd0 + t / 24);
    return angleTime(-acot(factor + tan(Math.abs(lat - decl))), t, false);
  };
  let t = { fajr: 5, sunrise: 6, dhuhr: 12, asr: 13, sunset: 18, maghrib: 18, isha: 18 };
  for (let i = 0; i < 2; i++) {
    t = {
      fajr: angleTime(spec.fajr, t.fajr, true),
      sunrise: angleTime(0.833, t.sunrise, true),
      dhuhr: midDay(t.dhuhr),
      asr: asrTime(t.asr),
      sunset: angleTime(0.833, t.sunset, false),
      maghrib: angleTime(spec.maghrib ?? 0.833, t.maghrib, false),
      isha: typeof spec.isha === "number" ? angleTime(spec.isha, t.isha, false) : t.isha,
    };
  }
  if (typeof spec.isha !== "number") t.isha = t.maghrib + spec.isha.minutes / 60;

  // far north/south: Fajr and Isha may not exist, or be absurd; take a part of the night instead
  const night = 24 + t.sunrise - t.sunset;
  if (s.high_lat !== "none" && isFinite(night)) {
    const part = (angle: number) => s.high_lat === "midnight" ? 1 / 2 : s.high_lat === "seventh" ? 1 / 7 : angle / 60;
    const fajrMax = part(spec.fajr) * night;
    if (!isFinite(t.fajr) || t.sunrise - t.fajr > fajrMax) t.fajr = t.sunrise - fajrMax;
    if (typeof spec.isha === "number") {
      const ishaMax = part(spec.isha) * night;
      if (!isFinite(t.isha) || t.isha - t.sunset > ishaMax) t.isha = t.sunset + ishaMax;
    }
    if (spec.maghrib) {
      const mMax = part(spec.maghrib) * night;
      if (!isFinite(t.maghrib) || t.maghrib - t.sunset > mMax) t.maghrib = t.sunset + mMax;
    }
  }

  // hours of the local solar day -> moments (UTC)
  const base = Date.UTC(y, m - 1, d);
  const at = (hours: number, offsetMin = 0) =>
    new Date(base + Math.round(((hours - lng / 15) * 60 + offsetMin) * 60) * 1000);
  const o = s.offsets;
  const out = {
    fajr: at(t.fajr, o.fajr), sunrise: at(t.sunrise, o.sunrise), dhuhr: at(t.dhuhr, o.dhuhr),
    asr: at(t.asr, o.asr), maghrib: at(t.maghrib, o.maghrib), isha: at(t.isha, o.isha),
  };
  // the night runs from sunset to tomorrow's Fajr; midnight and the last third split it
  const nextFajr = at(t.fajr + 24, o.fajr).getTime();
  const sunset = at(t.sunset).getTime();
  const span = nextFajr - sunset;
  return { ...out, midnight: new Date(sunset + span / 2), lastThird: new Date(sunset + (span * 2) / 3) };
}

// --------------------------------------------------------------- the day where the place is

/** The calendar date it is at `when` in `timeZone` (browser's own when null). */
export function dateIn(when: Date, timeZone: string | null): { y: number; m: number; d: number; weekday: number } {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: timeZone ?? undefined, year: "numeric", month: "numeric", day: "numeric", weekday: "short",
  }).formatToParts(when);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  const weekday = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].indexOf(get("weekday"));
  return { y: Number(get("year")), m: Number(get("month")), d: Number(get("day")), weekday };
}

export function dayKey(p: { y: number; m: number; d: number }): string {
  return `${p.y}-${String(p.m).padStart(2, "0")}-${String(p.d).padStart(2, "0")}`;
}

export function addDays(p: { y: number; m: number; d: number }, n: number): { y: number; m: number; d: number } {
  const t = new Date(Date.UTC(p.y, p.m - 1, p.d + n));
  return { y: t.getUTCFullYear(), m: t.getUTCMonth() + 1, d: t.getUTCDate() };
}

export function timesFor(day: { y: number; m: number; d: number }, s: PrayerSettings): DayTimes {
  return prayerTimes(day.y, day.m, day.d, s);
}

export interface Moment {
  current: Exclude<PrayerName, "sunrise"> | null;   // whose time it is now (null between sunrise and Dhuhr)
  endsAt: Date | null;                              // when the current prayer's time ends
  next: PrayerName;                                 // the next time to come (sunrise counts: it ends Fajr)
  nextAt: Date;
  today: DayTimes;
}

/** What time of prayer it is at `now`, and what comes next. */
export function momentAt(now: Date, s: PrayerSettings): Moment {
  const day = dateIn(now, s.timezone);
  const today = timesFor(day, s);
  const yesterday = timesFor(addDays(day, -1), s);
  const tomorrow = timesFor(addDays(day, 1), s);
  const n = now.getTime();
  const seq: { name: PrayerName; at: Date }[] = [
    { name: "isha", at: yesterday.isha },
    ...PRAYERS.map((p) => ({ name: p, at: today[p] })),
    { name: "fajr", at: tomorrow.fajr },
    { name: "sunrise", at: tomorrow.sunrise },
  ];
  let i = 0;
  while (i + 1 < seq.length && seq[i + 1].at.getTime() <= n) i++;
  const cur = seq[i], nxt = seq[i + 1];
  return {
    current: cur.name === "sunrise" ? null : cur.name,
    endsAt: cur.name === "sunrise" ? null : nxt.at,
    next: nxt.name, nextAt: nxt.at, today,
  };
}

// --------------------------------------------------------------------- Qibla and the Hijri date

const KAABA = { lat: 21.4225, lng: 39.8262 };

/** Direction of the Kaaba from the place, in degrees clockwise from true north. */
export function qibla(lat: number, lng: number): number {
  const dl = KAABA.lng - lng;
  return fix(atan2(sin(dl), cos(lat) * tan(KAABA.lat) - sin(lat) * cos(dl)), 360);
}

/** Distance to Makkah in km (great circle). */
export function distanceToMakkah(lat: number, lng: number): number {
  const a = sin((KAABA.lat - lat) / 2) ** 2 + cos(lat) * cos(KAABA.lat) * sin((KAABA.lng - lng) / 2) ** 2;
  return 6371 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

export function hijri(when: Date, locale: string, timeZone: string | null): { text: string; month: number } {
  try {
    const tz = timeZone ?? undefined;
    const text = new Intl.DateTimeFormat(`${locale}-u-ca-islamic-umalqura`, { day: "numeric", month: "long", year: "numeric", timeZone: tz }).format(when);
    const month = Number(new Intl.DateTimeFormat("en-u-ca-islamic-umalqura-nu-latn", { month: "numeric", timeZone: tz }).format(when));
    return { text, month };
  } catch {
    return { text: "", month: 0 };
  }
}

// ------------------------------------------------------------------------------- places

export interface Place { name: string; bn?: string; lat: number; lng: number; tz: string; method: Method }

const BD = "Asia/Dhaka";
/** Places to pick from when the browser can't tell where it is (it can't on a plain http:// address). */
export const PLACES: Place[] = [
  ...([
    ["Dhaka", "ঢাকা", 23.8103, 90.4125], ["Chattogram", "চট্টগ্রাম", 22.3569, 91.7832], ["Sylhet", "সিলেট", 24.8949, 91.8687],
    ["Khulna", "খুলনা", 22.8456, 89.5403], ["Rajshahi", "রাজশাহী", 24.3745, 88.6042], ["Barishal", "বরিশাল", 22.701, 90.3535],
    ["Rangpur", "রংপুর", 25.7439, 89.2752], ["Mymensingh", "ময়মনসিংহ", 24.7471, 90.4203], ["Cumilla", "কুমিল্লা", 23.4607, 91.1809],
    ["Gazipur", "গাজীপুর", 23.9999, 90.4203], ["Narayanganj", "নারায়ণগঞ্জ", 23.6238, 90.5], ["Cox's Bazar", "কক্সবাজার", 21.4272, 92.0058],
    ["Bogura", "বগুড়া", 24.8465, 89.3773], ["Jashore", "যশোর", 23.1664, 89.2081], ["Dinajpur", "দিনাজপুর", 25.6217, 88.6354],
    ["Tangail", "টাঙ্গাইল", 24.2513, 89.9167], ["Noakhali", "নোয়াখালী", 22.8696, 91.0995], ["Feni", "ফেনী", 23.0159, 91.3976],
    ["Brahmanbaria", "ব্রাহ্মণবাড়িয়া", 23.9571, 91.1119], ["Kushtia", "কুষ্টিয়া", 23.9013, 89.1204], ["Pabna", "পাবনা", 24.0064, 89.2372],
    ["Faridpur", "ফরিদপুর", 23.607, 89.8429], ["Habiganj", "হবিগঞ্জ", 24.3749, 91.4155], ["Moulvibazar", "মৌলভীবাজার", 24.4829, 91.7774],
    ["Sunamganj", "সুনামগঞ্জ", 25.0658, 91.395], ["Kishoreganj", "কিশোরগঞ্জ", 24.4449, 90.7766], ["Jamalpur", "জামালপুর", 24.9375, 89.9378],
    ["Bhola", "ভোলা", 22.6859, 90.6482], ["Patuakhali", "পটুয়াখালী", 22.3596, 90.3299], ["Satkhira", "সাতক্ষীরা", 22.7185, 89.0705],
    ["Chandpur", "চাঁদপুর", 23.2333, 90.6713], ["Lakshmipur", "লক্ষ্মীপুর", 22.9447, 90.8282], ["Narsingdi", "নরসিংদী", 23.9322, 90.7151],
    ["Munshiganj", "মুন্সীগঞ্জ", 23.5422, 90.5305], ["Manikganj", "মানিকগঞ্জ", 23.8644, 90.0047], ["Sirajganj", "সিরাজগঞ্জ", 24.4534, 89.7007],
    ["Naogaon", "নওগাঁ", 24.8133, 88.934], ["Chapainawabganj", "চাঁপাইনবাবগঞ্জ", 24.5965, 88.2775], ["Thakurgaon", "ঠাকুরগাঁও", 26.0337, 88.4617],
    ["Panchagarh", "পঞ্চগড়", 26.3411, 88.5542], ["Kurigram", "কুড়িগ্রাম", 25.8054, 89.6362], ["Gaibandha", "গাইবান্ধা", 25.3297, 89.543],
    ["Nilphamari", "নীলফামারী", 25.931, 88.856], ["Lalmonirhat", "লালমনিরহাট", 25.9923, 89.2847], ["Rangamati", "রাঙ্গামাটি", 22.6574, 92.1733],
    ["Bandarban", "বান্দরবান", 22.1953, 92.2184], ["Khagrachhari", "খাগড়াছড়ি", 23.1193, 91.9847],
  ] as [string, string, number, number][]).map(([name, bn, lat, lng]) => ({ name, bn, lat, lng, tz: BD, method: "karachi" as Method })),
  ...([
    ["Makkah", "মক্কা", 21.4225, 39.8262, "Asia/Riyadh", "makkah"], ["Madinah", "মদিনা", 24.4672, 39.6111, "Asia/Riyadh", "makkah"],
    ["Riyadh", "রিয়াদ", 24.7136, 46.6753, "Asia/Riyadh", "makkah"], ["Jeddah", "জেদ্দা", 21.4858, 39.1925, "Asia/Riyadh", "makkah"],
    ["Dubai", "দুবাই", 25.2048, 55.2708, "Asia/Dubai", "dubai"], ["Abu Dhabi", "আবুধাবি", 24.4539, 54.3773, "Asia/Dubai", "dubai"],
    ["Doha", "দোহা", 25.2854, 51.531, "Asia/Qatar", "dubai"], ["Kuwait City", "কুয়েত সিটি", 29.3759, 47.9774, "Asia/Kuwait", "dubai"],
    ["Muscat", "মাস্কাট", 23.588, 58.3829, "Asia/Muscat", "dubai"], ["Manama", "মানামা", 26.2285, 50.586, "Asia/Bahrain", "dubai"],
    ["Kuala Lumpur", "কুয়ালালামপুর", 3.139, 101.6869, "Asia/Kuala_Lumpur", "singapore"], ["Singapore", "সিঙ্গাপুর", 1.3521, 103.8198, "Asia/Singapore", "singapore"],
    ["Jakarta", "জাকার্তা", -6.2088, 106.8456, "Asia/Jakarta", "singapore"], ["Kolkata", "কলকাতা", 22.5726, 88.3639, "Asia/Kolkata", "karachi"],
    ["Delhi", "দিল্লি", 28.6139, 77.209, "Asia/Kolkata", "karachi"], ["Karachi", "করাচি", 24.8607, 67.0011, "Asia/Karachi", "karachi"],
    ["Lahore", "লাহোর", 31.5204, 74.3587, "Asia/Karachi", "karachi"], ["Istanbul", "ইস্তানবুল", 41.0082, 28.9784, "Europe/Istanbul", "turkey"],
    ["Cairo", "কায়রো", 30.0444, 31.2357, "Africa/Cairo", "egypt"], ["London", "লন্ডন", 51.5074, -0.1278, "Europe/London", "mwl"],
    ["Birmingham", "বার্মিংহাম", 52.4862, -1.8904, "Europe/London", "mwl"], ["Paris", "প্যারিস", 48.8566, 2.3522, "Europe/Paris", "mwl"],
    ["Rome", "রোম", 41.9028, 12.4964, "Europe/Rome", "mwl"], ["Berlin", "বার্লিন", 52.52, 13.405, "Europe/Berlin", "mwl"],
    ["New York", "নিউ ইয়র্ক", 40.7128, -74.006, "America/New_York", "isna"], ["Toronto", "টরন্টো", 43.6532, -79.3832, "America/Toronto", "isna"],
    ["Los Angeles", "লস অ্যাঞ্জেলেস", 34.0522, -118.2437, "America/Los_Angeles", "isna"], ["Sydney", "সিডনি", -33.8688, 151.2093, "Australia/Sydney", "mwl"],
    ["Tokyo", "টোকিও", 35.6762, 139.6503, "Asia/Tokyo", "mwl"],
  ] as [string, string, number, number, string, Method][]).map(([name, bn, lat, lng, tz, method]) => ({ name, bn, lat, lng, tz, method })),
];

/** A sensible method for where the person is (they can change it). */
export function methodFor(tz: string | null): Method {
  if (!tz) return "karachi";
  if (tz === "Asia/Riyadh") return "makkah";
  if (/^Asia\/(Dubai|Qatar|Kuwait|Muscat|Bahrain)$/.test(tz)) return "dubai";
  if (/^Asia\/(Kuala_Lumpur|Singapore|Jakarta|Makassar|Jayapura|Brunei)$/.test(tz)) return "singapore";
  if (tz === "Europe/Istanbul") return "turkey";
  if (tz === "Africa/Cairo") return "egypt";
  if (tz === "Asia/Tehran") return "tehran";
  if (tz.startsWith("America/")) return "isna";
  if (tz.startsWith("Europe/") || tz.startsWith("Australia/")) return "mwl";
  return "karachi";
}
