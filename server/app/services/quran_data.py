"""The 114 surahs: number, transliterated name, Arabic name, Bangla name, ayah count, and where
it was revealed (M = Makkah, Md = Madinah). Used to name recitation files and to show the list."""
from __future__ import annotations

import re
import unicodedata

_RAW = """\
1|Al-Fatihah|الفاتحة|আল-ফাতিহা|7|M
2|Al-Baqarah|البقرة|আল-বাকারা|286|Md
3|Aal-Imran|آل عمران|আলে-ইমরান|200|Md
4|An-Nisa|النساء|আন-নিসা|176|Md
5|Al-Ma'idah|المائدة|আল-মায়িদা|120|Md
6|Al-An'am|الأنعام|আল-আনআম|165|M
7|Al-A'raf|الأعراف|আল-আ'রাফ|206|M
8|Al-Anfal|الأنفال|আল-আনফাল|75|Md
9|At-Tawbah|التوبة|আত-তাওবা|129|Md
10|Yunus|يونس|ইউনুস|109|M
11|Hud|هود|হুদ|123|M
12|Yusuf|يوسف|ইউসুফ|111|M
13|Ar-Ra'd|الرعد|আর-রা'দ|43|Md
14|Ibrahim|إبراهيم|ইবরাহীম|52|M
15|Al-Hijr|الحجر|আল-হিজর|99|M
16|An-Nahl|النحل|আন-নাহল|128|M
17|Al-Isra|الإسراء|আল-ইসরা|111|M
18|Al-Kahf|الكهف|আল-কাহফ|110|M
19|Maryam|مريم|মারইয়াম|98|M
20|Ta-Ha|طه|ত্বা-হা|135|M
21|Al-Anbiya|الأنبياء|আল-আম্বিয়া|112|M
22|Al-Hajj|الحج|আল-হাজ্জ|78|Md
23|Al-Mu'minun|المؤمنون|আল-মু'মিনূন|118|M
24|An-Nur|النور|আন-নূর|64|Md
25|Al-Furqan|الفرقان|আল-ফুরকান|77|M
26|Ash-Shu'ara|الشعراء|আশ-শু'আরা|227|M
27|An-Naml|النمل|আন-নামল|93|M
28|Al-Qasas|القصص|আল-কাসাস|88|M
29|Al-Ankabut|العنكبوت|আল-আনকাবূত|69|M
30|Ar-Rum|الروم|আর-রূম|60|M
31|Luqman|لقمان|লুকমান|34|M
32|As-Sajdah|السجدة|আস-সাজদাহ|30|M
33|Al-Ahzab|الأحزاب|আল-আহযাব|73|Md
34|Saba|سبأ|সাবা|54|M
35|Fatir|فاطر|ফাতির|45|M
36|Ya-Sin|يس|ইয়াসীন|83|M
37|As-Saffat|الصافات|আস-সাফফাত|182|M
38|Sad|ص|সোয়াদ|88|M
39|Az-Zumar|الزمر|আয-যুমার|75|M
40|Ghafir|غافر|গাফির|85|M
41|Fussilat|فصلت|ফুসসিলাত|54|M
42|Ash-Shura|الشورى|আশ-শূরা|53|M
43|Az-Zukhruf|الزخرف|আয-যুখরুফ|89|M
44|Ad-Dukhan|الدخان|আদ-দুখান|59|M
45|Al-Jathiyah|الجاثية|আল-জাসিয়া|37|M
46|Al-Ahqaf|الأحقاف|আল-আহকাফ|35|M
47|Muhammad|محمد|মুহাম্মাদ|38|Md
48|Al-Fath|الفتح|আল-ফাতহ|29|Md
49|Al-Hujurat|الحجرات|আল-হুজুরাত|18|Md
50|Qaf|ق|ক্বাফ|45|M
51|Adh-Dhariyat|الذاريات|আয-যারিয়াত|60|M
52|At-Tur|الطور|আত-তূর|49|M
53|An-Najm|النجم|আন-নাজম|62|M
54|Al-Qamar|القمر|আল-ক্বামার|55|M
55|Ar-Rahman|الرحمن|আর-রাহমান|78|Md
56|Al-Waqi'ah|الواقعة|আল-ওয়াকি'আ|96|M
57|Al-Hadid|الحديد|আল-হাদীদ|29|Md
58|Al-Mujadilah|المجادلة|আল-মুজাদালাহ|22|Md
59|Al-Hashr|الحشر|আল-হাশর|24|Md
60|Al-Mumtahanah|الممتحنة|আল-মুমতাহিনা|13|Md
61|As-Saff|الصف|আস-সাফ|14|Md
62|Al-Jumu'ah|الجمعة|আল-জুমু'আ|11|Md
63|Al-Munafiqun|المنافقون|আল-মুনাফিকূন|11|Md
64|At-Taghabun|التغابن|আত-তাগাবুন|18|Md
65|At-Talaq|الطلاق|আত-ত্বালাক|12|Md
66|At-Tahrim|التحريم|আত-তাহরীম|12|Md
67|Al-Mulk|الملك|আল-মুলক|30|M
68|Al-Qalam|القلم|আল-ক্বলম|52|M
69|Al-Haqqah|الحاقة|আল-হাক্কাহ|52|M
70|Al-Ma'arij|المعارج|আল-মা'আরিজ|44|M
71|Nuh|نوح|নূহ|28|M
72|Al-Jinn|الجن|আল-জিন|28|M
73|Al-Muzzammil|المزمل|আল-মুযযাম্মিল|20|M
74|Al-Muddaththir|المدثر|আল-মুদ্দাসসির|56|M
75|Al-Qiyamah|القيامة|আল-ক্বিয়ামাহ|40|M
76|Al-Insan|الإنسان|আল-ইনসান|31|Md
77|Al-Mursalat|المرسلات|আল-মুরসালাত|50|M
78|An-Naba|النبأ|আন-নাবা|40|M
79|An-Nazi'at|النازعات|আন-নাযি'আত|46|M
80|Abasa|عبس|আবাসা|42|M
81|At-Takwir|التكوير|আত-তাকভীর|29|M
82|Al-Infitar|الانفطار|আল-ইনফিতার|19|M
83|Al-Mutaffifin|المطففين|আল-মুতাফফিফীন|36|M
84|Al-Inshiqaq|الانشقاق|আল-ইনশিক্বাক|25|M
85|Al-Buruj|البروج|আল-বুরূজ|22|M
86|At-Tariq|الطارق|আত-ত্বারিক|17|M
87|Al-A'la|الأعلى|আল-আ'লা|19|M
88|Al-Ghashiyah|الغاشية|আল-গাশিয়াহ|26|M
89|Al-Fajr|الفجر|আল-ফাজর|30|M
90|Al-Balad|البلد|আল-বালাদ|20|M
91|Ash-Shams|الشمس|আশ-শামস|15|M
92|Al-Layl|الليل|আল-লাইল|21|M
93|Ad-Duha|الضحى|আদ-দুহা|11|M
94|Ash-Sharh|الشرح|আশ-শারহ|8|M
95|At-Tin|التين|আত-তীন|8|M
96|Al-Alaq|العلق|আল-আলাক|19|M
97|Al-Qadr|القدر|আল-ক্বদর|5|M
98|Al-Bayyinah|البينة|আল-বাইয়্যিনাহ|8|Md
99|Az-Zalzalah|الزلزلة|আয-যিলযাল|8|Md
100|Al-Adiyat|العاديات|আল-আদিয়াত|11|M
101|Al-Qari'ah|القارعة|আল-ক্বারি'আহ|11|M
102|At-Takathur|التكاثر|আত-তাকাসুর|8|M
103|Al-Asr|العصر|আল-আসর|3|M
104|Al-Humazah|الهمزة|আল-হুমাযাহ|9|M
105|Al-Fil|الفيل|আল-ফীল|5|M
106|Quraysh|قريش|কুরাইশ|4|M
107|Al-Ma'un|الماعون|আল-মা'ঊন|7|M
108|Al-Kawthar|الكوثر|আল-কাওসার|3|M
109|Al-Kafirun|الكافرون|আল-কাফিরূন|6|M
110|An-Nasr|النصر|আন-নাসর|3|Md
111|Al-Masad|المسد|আল-মাসাদ|5|M
112|Al-Ikhlas|الإخلاص|আল-ইখলাস|4|M
113|Al-Falaq|الفلق|আল-ফালাক্ব|5|M
114|An-Nas|الناس|আন-নাস|6|M
"""

SURAHS: list[dict] = []
for _line in _RAW.strip().splitlines():
    _n, _name, _ar, _bn, _ayahs, _place = _line.split("|")
    SURAHS.append({"number": int(_n), "name": _name, "arabic": _ar, "bangla": _bn,
                   "ayahs": int(_ayahs), "place": "makkah" if _place == "M" else "madinah"})


def _key(s: str) -> str:
    """'Al-Baqarah' / 'al_baqara' / 'Surah Baqarah' -> 'baqara' (for matching file names)."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"^(surah?|sura)\b", "", s.strip(" -_."))
    s = re.sub(r"[^a-z]", "", s)
    s = re.sub(r"^(al|an|ar|as|at|ad|adh|az|ash)(?=[a-z]{3})", "", s)
    s = s.replace("ee", "i").replace("oo", "u").replace("ou", "u").replace("kh", "k").replace("q", "k")
    s = re.sub(r"(.)\1", r"\1", s)
    return s.rstrip("h") or s


_BY_NAME: dict[str, int] = {}
for _s in SURAHS:
    _BY_NAME.setdefault(_key(_s["name"]), _s["number"])
for _alias, _n in {"fatiha": 1, "imran": 3, "alimran": 3, "maidah": 5, "anam": 6, "araf": 7, "tauba": 9,
                   "taubah": 9, "bara": 9, "baraah": 9, "rad": 13, "bani israil": 17, "baniisrail": 17,
                   "isra": 17, "taha": 20, "muminun": 23, "muminoon": 23, "shuara": 26, "ankabut": 29,
                   "sajda": 32, "yasin": 36, "yaseen": 36, "saad": 38, "mumin": 40, "hamimsajda": 41,
                   "fussilat": 41, "dhariyat": 51, "zariyat": 51, "rahman": 55, "waqia": 56, "waqiah": 56,
                   "mujadila": 58, "mumtahina": 60, "jumua": 62, "jumuah": 62, "munafiqun": 63,
                   "dahr": 76, "insan": 76, "naba": 78, "naziat": 79, "takwir": 81, "infitar": 82,
                   "mutaffifin": 83, "inshiqaq": 84, "buruj": 85, "tariq": 86, "ala": 87, "ghashiya": 88,
                   "inshirah": 94, "alamnashrah": 94, "sharh": 94, "tin": 95, "alaq": 96, "iqra": 96,
                   "qadr": 97, "bayyina": 98, "zilzal": 99, "zalzala": 99, "adiyat": 100, "qaria": 101,
                   "takathur": 102, "asr": 103, "humaza": 104, "fil": 105, "quraish": 106, "quraysh": 106,
                   "maun": 107, "kauthar": 108, "kawthar": 108, "kausar": 108, "kafirun": 109, "kafiroon": 109,
                   "nasr": 110, "lahab": 111, "masad": 111, "ikhlas": 112, "falaq": 113, "nas": 114}.items():
    _BY_NAME.setdefault(_key(_alias), _n)

# 001.mp3, 001 - Al-Fatiha.mp3, Surah 2, 002_al_baqarah, s001, 018-Kahf
_NUM = re.compile(r"^(?:s(?:urah?|ura)?[\s._\-]*)?0*(\d{1,3})(?!\d)\b|^(?:s(?:urah?|ura)?[\s._\-]*)?0*(\d{1,3})(?=[\s._\-)])", re.I)
_AYAH_FILE = re.compile(r"^(\d{3})(\d{3})$")  # everyayah.com style: 002255.mp3


def parse_file(stem: str, track_no: int | None = None) -> tuple[int | None, int | None]:
    """(surah, ayah) a recitation file holds; ayah is set for one-file-per-ayah collections."""
    s = re.sub(r"\s*[(\[{].*?[)\]}]", " ", stem).strip()  # "(Sudais)", "[128kbps]"
    m = _AYAH_FILE.match(s)
    if m and 1 <= int(m.group(1)) <= 114:
        return int(m.group(1)), int(m.group(2))
    m = _NUM.match(s)
    if m:
        n = int(m.group(1) or m.group(2))
        if 1 <= n <= 114:
            return n, None
    m = re.search(r"\b(?:surah?|sura)[\s._\-]*0*(\d{1,3})\b", s, re.I)
    if m and 1 <= int(m.group(1)) <= 114:
        return int(m.group(1)), None
    name = re.sub(r"^[\d\s._\-]+", "", s)
    n = _BY_NAME.get(_key(name))
    if n:
        return n, None
    m = re.search(r"\b(?:surah?|sura)[\s._\-]+(.+)$", s, re.I)  # "Mishary - Surah Ar-Rahman"
    if m and (n := _BY_NAME.get(_key(m.group(1)))):
        return n, None
    for part in re.split(r"\s+-\s+|_-_", s):  # "Ar-Rahman - Mishary"
        if (n := _BY_NAME.get(_key(part))):
            return n, None
    if track_no and 1 <= track_no <= 114:
        return track_no, None
    return None, None
